"""Tests for ISCSIDiskDevice and ISCSIDiskTarget."""
from __future__ import annotations

import pytest
from unittest.mock import Mock

from truenas_pylibvirt.device import ISCSIDiskDevice, ISCSIDiskTarget
from truenas_pylibvirt.device.base import QemuArgsContext
from truenas_pylibvirt.device.delegate import DeviceDelegate


VALID_IQN_TARGET = "iqn.2026-06.net.ixsystems.tnguest:ha000-d000"
VALID_IQN_INITIATOR = "iqn.2026-06.net.ixsystems.tnguest:ha000"
PORTAL_V4 = "10.99.0.100"
PORTAL_V6 = "2001:db8::1"

CTX_Q35 = QemuArgsContext(machine_type="pc-q35-10.0")
CTX_VIRT = QemuArgsContext(machine_type="virt-9.2")
CTX_I440FX = QemuArgsContext(machine_type="pc-i440fx-9.2")
CTX_UNKNOWN = QemuArgsContext(machine_type=None)


def _device(
    portal_address=PORTAL_V4,
    targets=None,
    initiator_iqn=VALID_IQN_INITIATOR,
    controller_slot=0x15,
    delegate=None,
):
    if targets is None:
        targets = [ISCSIDiskTarget(iqn=VALID_IQN_TARGET)]
    if delegate is None:
        d = Mock(spec=DeviceDelegate)
        d.is_available = Mock(return_value=True)
        delegate = d
    return ISCSIDiskDevice(
        portal_address=portal_address,
        targets=targets,
        initiator_iqn=initiator_iqn,
        controller_slot=controller_slot,
        device_delegate=delegate,
    )


def test_xml_returns_empty(device_context, mock_device_delegate):
    """ISCSIDiskDevice uses qemu_args() not xml(); xml() must return an empty list
    so no spurious entries appear in the libvirt <devices> section."""
    d = _device(delegate=mock_device_delegate)
    assert d.xml(device_context) == []


def test_qemu_args_single_target_single_lun():
    """A single target with one LUN emits one -iscsi flag, one virtio-scsi-pci
    controller, one -drive, and one scsi-block device."""
    d = _device()
    args = d.qemu_args(CTX_Q35)

    assert "-iscsi" in args
    idx = args.index("-iscsi")
    assert args[idx + 1] == f"initiator-name={VALID_IQN_INITIATOR}"

    device_args = [args[i + 1] for i, a in enumerate(args) if a == "-device"]
    assert any("virtio-scsi-pci" in a for a in device_args)
    assert any("scsi-block" in a for a in device_args)

    drive_args = [args[i + 1] for i, a in enumerate(args) if a == "-drive"]
    assert any(PORTAL_V4 in a and VALID_IQN_TARGET in a for a in drive_args)


def test_qemu_args_multiple_targets():
    """With N targets (each with one LUN) the device emits N -drive/-device
    scsi-block pairs, all sharing one virtio-scsi-pci controller."""
    iqns = [
        "iqn.2026-06.net.ixsystems.tnguest:ha000-d000",
        "iqn.2026-06.net.ixsystems.tnguest:ha000-d001",
        "iqn.2026-06.net.ixsystems.tnguest:ha000-d002",
    ]
    d = _device(targets=[ISCSIDiskTarget(iqn=q) for q in iqns])
    args = d.qemu_args(CTX_Q35)

    drive_args = [args[i + 1] for i, a in enumerate(args) if a == "-drive"]
    assert len(drive_args) == 3
    for iqn in iqns:
        assert any(iqn in a for a in drive_args)

    scsi_block_args = [
        args[i + 1] for i, a in enumerate(args)
        if a == "-device" and "scsi-block" in args[i + 1]
    ]
    assert len(scsi_block_args) == 3
    controller_id = f"scsi-iscsi-{0x15:x}"
    assert all(f"bus={controller_id}.0" in a for a in scsi_block_args)


def test_qemu_args_multiple_luns_per_target():
    """Multiple LUNs on one target each produce a separate -drive/-device pair."""
    d = _device(targets=[ISCSIDiskTarget(iqn=VALID_IQN_TARGET, luns=[0, 1, 2])])
    args = d.qemu_args(CTX_Q35)

    drive_args = [args[i + 1] for i, a in enumerate(args) if a == "-drive"]
    assert len(drive_args) == 3
    assert any("/0," in a or a.endswith("/0") for a in drive_args)
    assert any("/1," in a or a.endswith("/1") for a in drive_args)
    assert any("/2," in a or a.endswith("/2") for a in drive_args)


def test_qemu_args_custom_slot():
    """controller_slot controls both the PCI addr= value and the controller ID
    embedded in device/bus references, allowing multiple iSCSI devices to
    coexist on the root bus without address conflicts."""
    d = _device(controller_slot=0x10)
    args = d.qemu_args(CTX_Q35)
    device_args = [args[i + 1] for i, a in enumerate(args) if a == "-device"]
    assert any("addr=0x10" in a for a in device_args)
    assert any("scsi-iscsi-10" in a for a in device_args)


@pytest.mark.parametrize("ctx,expected_bus", [
    # q35 is PCIe-native
    (CTX_Q35,     "pcie.0"),
    # aarch64 virt machine is also PCIe-native (pcie-root), not i440fx
    (CTX_VIRT,    "pcie.0"),
    # i440fx uses the legacy PCI root bus
    (CTX_I440FX,  "pci.0"),
    # unknown machine type defaults conservatively to pci.0
    (CTX_UNKNOWN, "pci.0"),
])
def test_qemu_args_root_bus(ctx, expected_bus):
    """The virtio-scsi-pci controller is attached to the correct root bus for
    each machine type: pcie.0 for q35 and aarch64 virt, pci.0 otherwise."""
    d = _device()
    args = d.qemu_args(ctx)
    device_args = [args[i + 1] for i, a in enumerate(args) if a == "-device"]
    controller_args = [a for a in device_args if "virtio-scsi-pci" in a]
    assert len(controller_args) == 1
    assert f"bus={expected_bus}" in controller_args[0]


def test_qemu_args_ipv6_portal():
    """IPv6 portal addresses are bracketed in the iSCSI URI as required by
    RFC 3986 (e.g. iscsi://[2001:db8::1]/iqn.../0)."""
    d = _device(portal_address=PORTAL_V6)
    args = d.qemu_args(CTX_Q35)
    drive_args = [args[i + 1] for i, a in enumerate(args) if a == "-drive"]
    assert all(f"[{PORTAL_V6}]" in a for a in drive_args)


def test_pci_slot():
    """pci_slot() returns (0, controller_slot) -- bus 0 is the root bus, so the
    conflict checker can detect clashes between the iSCSI controller and NICs
    pinned to the root bus."""
    d = _device(controller_slot=0x15)
    assert d.pci_slot() == (0, 0x15)


def test_identity():
    """identity() returns a string incorporating portal_address and the first
    target IQN, uniquely identifying the attachment within a VM's device list."""
    d = _device()
    assert d.identity() == f"iscsi:{PORTAL_V4}:{VALID_IQN_TARGET}"


def test_is_available():
    """is_available_impl() returns True unconditionally; reachability of the
    iSCSI target is not checked at device-creation time."""
    d = _device()
    assert d.is_available_impl() is True


def test_iscsi_disk_target_default_luns():
    """ISCSIDiskTarget defaults to luns=[0] when not specified."""
    t = ISCSIDiskTarget(iqn=VALID_IQN_TARGET)
    assert t.luns == [0]


@pytest.mark.parametrize("portal_address,targets,initiator_iqn,controller_slot,expected_errors", [
    # valid
    (PORTAL_V4, [ISCSIDiskTarget(iqn=VALID_IQN_TARGET)], VALID_IQN_INITIATOR, 0x15, []),
    # valid IPv6
    (PORTAL_V6, [ISCSIDiskTarget(iqn=VALID_IQN_TARGET)], VALID_IQN_INITIATOR, 0x15, []),
    # bad IP
    ("not-an-ip", [ISCSIDiskTarget(iqn=VALID_IQN_TARGET)], VALID_IQN_INITIATOR, 0x15, ["portal_address"]),
    # empty targets list
    (PORTAL_V4, [], VALID_IQN_INITIATOR, 0x15, ["targets"]),
    # malformed target IQN
    (PORTAL_V4, [ISCSIDiskTarget(iqn="not-an-iqn")], VALID_IQN_INITIATOR, 0x15, ["targets.0.iqn"]),
    # empty luns list on a target
    (PORTAL_V4, [ISCSIDiskTarget(iqn=VALID_IQN_TARGET, luns=[])], VALID_IQN_INITIATOR, 0x15, ["targets.0.luns"]),
    # negative lun
    (PORTAL_V4, [ISCSIDiskTarget(iqn=VALID_IQN_TARGET, luns=[-1])], VALID_IQN_INITIATOR, 0x15, ["targets.0.luns.0"]),
    # malformed initiator IQN
    (PORTAL_V4, [ISCSIDiskTarget(iqn=VALID_IQN_TARGET)], "not-an-iqn", 0x15, ["initiator_iqn"]),
    # controller_slot = 0 (below minimum)
    (PORTAL_V4, [ISCSIDiskTarget(iqn=VALID_IQN_TARGET)], VALID_IQN_INITIATOR, 0, ["controller_slot"]),
    # controller_slot = 31 (above maximum)
    (PORTAL_V4, [ISCSIDiskTarget(iqn=VALID_IQN_TARGET)], VALID_IQN_INITIATOR, 31, ["controller_slot"]),
    # QEMU option-string injection via comma in target IQN
    (PORTAL_V4, [ISCSIDiskTarget(iqn="iqn.2026-06.net.x:a,readonly=on")],
        VALID_IQN_INITIATOR, 0x15, ["targets.0.iqn"]),
    # QEMU option-string injection via comma+file= in target IQN
    (PORTAL_V4, [ISCSIDiskTarget(iqn="iqn.2026-06.net.x:a,file=/etc/shadow")],
        VALID_IQN_INITIATOR, 0x15, ["targets.0.iqn"]),
    # QEMU option-string injection via '=' in target IQN
    (PORTAL_V4, [ISCSIDiskTarget(iqn="iqn.2026-06.net.x:a=b")],
        VALID_IQN_INITIATOR, 0x15, ["targets.0.iqn"]),
    # QEMU option-string injection via comma in initiator IQN
    (PORTAL_V4, [ISCSIDiskTarget(iqn=VALID_IQN_TARGET)],
        "iqn.2026-06.net.x:a,password=pw", 0x15, ["initiator_iqn"]),
])
def test_validate(portal_address, targets, initiator_iqn, controller_slot, expected_errors, mock_device_delegate):
    """validate_impl() catches invalid addresses, malformed IQNs, empty/negative
    LUN lists, and out-of-range controller slots; valid configs produce no errors."""
    d = ISCSIDiskDevice(
        portal_address=portal_address,
        targets=targets,
        initiator_iqn=initiator_iqn,
        controller_slot=controller_slot,
        device_delegate=mock_device_delegate,
    )
    errors = d.validate()
    error_fields = [e[0] for e in errors]
    for f in expected_errors:
        assert f in error_fields, f"Expected error on '{f}', got: {errors}"
    if not expected_errors:
        assert errors == [], f"Expected no errors, got: {errors}"


# Defense-in-depth: qemu_args() must refuse to emit unsafe values even when
# validate() was never called (or the field was mutated after validation).
# These strings are chosen so that if they DID reach the arg list they would
# inject sibling key=value options into QEMU's comma-separated -drive / -iscsi
# option syntax.

def test_qemu_args_rejects_injecting_target_iqn():
    d = _device(targets=[ISCSIDiskTarget(iqn="iqn.2026-06.net.x:a,readonly=on")])
    with pytest.raises(ValueError, match="target IQN"):
        d.qemu_args(CTX_Q35)


def test_qemu_args_rejects_injecting_initiator_iqn():
    d = _device(initiator_iqn="iqn.2026-06.net.x:a,password=pw")
    with pytest.raises(ValueError, match="initiator IQN"):
        d.qemu_args(CTX_Q35)


def test_qemu_args_rejects_non_ip_portal():
    d = _device(portal_address="evil.example.com,file=/etc/shadow")
    with pytest.raises(ValueError, match="portal address"):
        d.qemu_args(CTX_Q35)


def test_qemu_args_rejects_field_mutated_after_construction():
    """Mutating an IQN after construction bypasses validate(); qemu_args()
    must still refuse to emit unsafe args."""
    d = _device()
    d.targets[0].iqn = "iqn.2026-06.net.x:a,readonly=on"
    with pytest.raises(ValueError, match="target IQN"):
        d.qemu_args(CTX_Q35)
