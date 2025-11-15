"""Tests for GPU device validation and XML generation."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
from xml.etree import ElementTree as ET

from truenas_pylibvirt.device import GPUDevice


def test_gpu_device_initialization(mock_device_delegate):
    """Test GPU device initialization."""
    device = GPUDevice(
        gpu_type="AMD",
        pci_address="0000:19:00.0",
        device_delegate=mock_device_delegate
    )

    assert device.gpu_type == "AMD"
    assert device.pci_address == "0000:19:00.0"
    assert device.gpu is not None


def test_gpu_device_identity(mock_device_delegate):
    """Test GPU device identity."""
    device = GPUDevice(
        gpu_type="AMD",
        pci_address="0000:19:00.0",
        device_delegate=mock_device_delegate
    )

    assert device.identity() == "AMD '0000:19:00.0'"


@patch('truenas_pylibvirt.device.gpu_utils.os.path.exists')
@patch('truenas_pylibvirt.device.gpu_utils.pathlib.Path')
@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_amd_gpu_xml_generation(
    mock_get_pci, mock_path, mock_exists,
    device_context, mock_device_delegate
):
    """Test AMD GPU XML generation."""
    # Mock render device path
    mock_render_dir = MagicMock()
    mock_render_node = MagicMock()
    mock_render_node.name = 'renderD128'
    mock_render_dir.iterdir.return_value = [mock_render_node]
    mock_path.return_value = mock_render_dir

    # Mock file existence checks
    mock_exists.side_effect = lambda path: path in ['/dev/kfd', '/dev/dri/renderD128']

    # Mock PCI device details
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['amdgpu'],
            'error': None,
        }
    }

    device = GPUDevice(
        gpu_type="AMD",
        pci_address="0000:19:00.0",
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)

    # Convert to string for easier assertion
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements)

    # xml() method should only return render device
    assert xml_str.count('<hostdev') == 1
    assert '/dev/dri/renderD128' in xml_str
    assert 'mode="capabilities"' in xml_str
    assert 'type="misc"' in xml_str

    # Check driver_xml separately (kfd device)
    driver_xml_elements = device.gpu.driver_xml()
    driver_xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in driver_xml_elements)
    assert '/dev/kfd' in driver_xml_str


@patch('truenas_pylibvirt.device.gpu_utils.normalize_pci_address')
@patch('truenas_pylibvirt.device.gpu_utils.os.path.exists')
@patch('truenas_pylibvirt.device.gpu_utils.pathlib.Path')
@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_amd_gpu_validation_success(
    mock_get_pci, mock_path, mock_exists, mock_normalize,
    mock_device_delegate
):
    """Test AMD GPU validation when all requirements are met."""
    # Mock normalize to return the same address
    mock_normalize.return_value = '0000:19:00.0'

    # Mock render device path
    mock_render_dir = MagicMock()
    mock_render_node = MagicMock()
    mock_render_node.name = 'renderD128'
    mock_render_dir.iterdir.return_value = [mock_render_node]
    mock_path.return_value = mock_render_dir

    # Mock file existence checks
    mock_exists.side_effect = lambda path: path in ['/dev/kfd', '/dev/dri/renderD128']

    # Mock PCI device details
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['amdgpu'],
            'error': None,
        }
    }

    # Mock get_gpus to return our GPU
    with patch('truenas_pylibvirt.device.gpu_utils.get_gpus') as mock_get_gpus:
        mock_get_gpus.return_value = [{
            'vendor': 'AMD',
            'addr': {'pci_slot': '0000:19:00.0'},
        }]

        device = GPUDevice(
            gpu_type="AMD",
            pci_address="0000:19:00.0",
            device_delegate=mock_device_delegate
        )

        errors = device.validate()
        assert len(errors) == 0


@patch('truenas_pylibvirt.device.gpu_utils.normalize_pci_address')
@patch('truenas_pylibvirt.device.gpu_utils.os.path.exists')
@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_amd_gpu_validation_missing_kfd(
    mock_get_pci, mock_exists, mock_normalize,
    mock_device_delegate
):
    """Test AMD GPU validation when /dev/kfd is missing."""
    # Mock normalize
    mock_normalize.return_value = '0000:19:00.0'

    # Mock that kfd doesn't exist
    mock_exists.return_value = False

    # Mock PCI device details
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['amdgpu'],
            'error': None,
        }
    }

    with patch('truenas_pylibvirt.device.gpu_utils.get_gpus') as mock_get_gpus:
        mock_get_gpus.return_value = [{
            'vendor': 'AMD',
            'addr': {'pci_slot': '0000:19:00.0'},
        }]

        device = GPUDevice(
            gpu_type="AMD",
            pci_address="0000:19:00.0",
            device_delegate=mock_device_delegate
        )

        errors = device.validate()
        assert len(errors) > 0
        assert any('/dev/kfd' in str(err) for err in errors)


@patch('truenas_pylibvirt.device.gpu_utils.normalize_pci_address')
@patch('truenas_pylibvirt.device.gpu_utils.pathlib.Path')
@patch('truenas_pylibvirt.device.gpu_utils.os.path.exists')
@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_amd_gpu_validation_missing_render_device(
    mock_get_pci, mock_exists, mock_path, mock_normalize,
    mock_device_delegate
):
    """Test AMD GPU validation when render device is missing."""
    # Mock normalize
    mock_normalize.return_value = '0000:19:00.0'

    # Mock that render directory is empty
    mock_render_dir = MagicMock()
    mock_render_dir.iterdir.return_value = []
    mock_path.return_value = mock_render_dir

    # Mock kfd exists
    mock_exists.side_effect = lambda path: path == '/dev/kfd'

    # Mock PCI device details
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['amdgpu'],
            'error': None,
        }
    }

    with patch('truenas_pylibvirt.device.gpu_utils.get_gpus') as mock_get_gpus:
        mock_get_gpus.return_value = [{
            'vendor': 'AMD',
            'addr': {'pci_slot': '0000:19:00.0'},
        }]

        device = GPUDevice(
            gpu_type="AMD",
            pci_address="0000:19:00.0",
            device_delegate=mock_device_delegate
        )

        errors = device.validate()
        assert len(errors) > 0
        assert any('compute/render node' in str(err) for err in errors)


@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_gpu_validation_invalid_pci_address(
    mock_get_pci,
    mock_device_delegate
):
    """Test GPU validation when PCI address is invalid."""
    # Mock that PCI device doesn't exist
    mock_get_pci.return_value = {}

    with patch('truenas_pylibvirt.device.gpu_utils.get_gpus') as mock_get_gpus:
        mock_get_gpus.return_value = []

        device = GPUDevice(
            gpu_type="AMD",
            pci_address="0000:99:00.0",
            device_delegate=mock_device_delegate
        )

        errors = device.validate()
        assert len(errors) > 0
        assert any('not found' in str(err) for err in errors)


@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_gpu_validation_wrong_gpu_type(
    mock_get_pci,
    mock_device_delegate
):
    """Test GPU validation when GPU type doesn't match."""
    # Mock PCI device exists
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['amdgpu'],
            'error': None,
        }
    }

    # Mock get_gpus returns a different vendor
    with patch('truenas_pylibvirt.device.gpu_utils.get_gpus') as mock_get_gpus:
        mock_get_gpus.return_value = [{
            'vendor': 'NVIDIA',  # Different from AMD
            'addr': {'pci_slot': '0000:19:00.0'},
        }]

        device = GPUDevice(
            gpu_type="AMD",
            pci_address="0000:19:00.0",
            device_delegate=mock_device_delegate
        )

        errors = device.validate()
        assert len(errors) > 0
        assert any('Unable to locate' in str(err) and 'AMD' in str(err) for err in errors)


@patch('truenas_pylibvirt.device.gpu_utils.normalize_pci_address')
@patch('truenas_pylibvirt.device.gpu_utils.os.path.exists')
@patch('truenas_pylibvirt.device.gpu_utils.pathlib.Path')
@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_amd_gpu_availability_check(
    mock_get_pci, mock_path, mock_exists, mock_normalize,
    mock_device_delegate
):
    """Test AMD GPU availability check."""
    # Mock normalize
    mock_normalize.return_value = '0000:19:00.0'

    # Mock render device path
    mock_render_dir = MagicMock()
    mock_render_node = MagicMock()
    mock_render_node.name = 'renderD128'
    mock_render_dir.iterdir.return_value = [mock_render_node]
    mock_path.return_value = mock_render_dir

    # Mock file existence checks
    mock_exists.side_effect = lambda path: path in ['/dev/kfd', '/dev/dri/renderD128']

    # Mock PCI device details with amdgpu driver
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['amdgpu'],
            'error': None,
        }
    }

    device = GPUDevice(
        gpu_type="AMD",
        pci_address="0000:19:00.0",
        device_delegate=mock_device_delegate
    )

    assert device.is_available() is True


@patch('truenas_pylibvirt.device.gpu_utils.os.path.exists')
@patch('truenas_pylibvirt.device.gpu_utils.pathlib.Path')
@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_amd_gpu_not_available_vfio(
    mock_get_pci, mock_path, mock_exists,
    mock_device_delegate
):
    """Test AMD GPU is not available when bound to vfio-pci."""
    # Mock render device path
    mock_render_dir = MagicMock()
    mock_render_node = MagicMock()
    mock_render_node.name = 'renderD128'
    mock_render_dir.iterdir.return_value = [mock_render_node]
    mock_path.return_value = mock_render_dir

    # Mock file existence checks
    mock_exists.side_effect = lambda path: path in ['/dev/kfd', '/dev/dri/renderD128']

    # Mock PCI device details with vfio-pci driver (not available)
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['vfio-pci'],
            'error': None,
        }
    }

    device = GPUDevice(
        gpu_type="AMD",
        pci_address="0000:19:00.0",
        device_delegate=mock_device_delegate
    )

    assert device.is_available() is False


@patch('truenas_pylibvirt.device.gpu_utils.os.path.exists')
@patch('truenas_pylibvirt.device.gpu_utils.pathlib.Path')
@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_amd_gpu_render_device_path_property(
    mock_get_pci, mock_path, mock_exists,
    mock_device_delegate
):
    """Test that render_device_path property returns correct /dev path."""
    # Mock render device path
    mock_render_dir = MagicMock()
    mock_render_node = MagicMock()
    mock_render_node.name = 'renderD128'
    mock_render_dir.iterdir.return_value = [mock_render_node]
    mock_path.return_value = mock_render_dir

    # Mock file existence
    mock_exists.side_effect = lambda path: path in ['/dev/kfd', '/dev/dri/renderD128']

    # Mock PCI device details
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['amdgpu'],
            'error': None,
        }
    }

    device = GPUDevice(
        gpu_type="AMD",
        pci_address="0000:19:00.0",
        device_delegate=mock_device_delegate
    )

    # Access the render_device_path through the gpu object
    render_path = device.gpu.render_device_path
    assert render_path == '/dev/dri/renderD128'
    assert not render_path.startswith('/sys/')  # Should not be sysfs path


@patch('truenas_pylibvirt.device.gpu_utils.os.path.exists')
@patch('truenas_pylibvirt.device.gpu_utils.pathlib.Path')
@patch('truenas_pylibvirt.device.gpu_utils.get_single_pci_device_details')
def test_amd_gpu_multiple_render_nodes(
    mock_get_pci, mock_path, mock_exists,
    device_context, mock_device_delegate
):
    """Test AMD GPU with multiple render nodes (should pick first one starting with 'render')."""
    # Mock multiple nodes in drm directory
    mock_render_dir = MagicMock()
    mock_card_node = MagicMock()
    mock_card_node.name = 'card1'
    mock_render_node = MagicMock()
    mock_render_node.name = 'renderD128'
    mock_control_node = MagicMock()
    mock_control_node.name = 'controlD65'
    mock_render_dir.iterdir.return_value = [mock_card_node, mock_render_node, mock_control_node]
    mock_path.return_value = mock_render_dir

    # Mock file existence
    mock_exists.side_effect = lambda path: path in ['/dev/kfd', '/dev/dri/renderD128']

    # Mock PCI device details
    mock_get_pci.return_value = {
        '0000:19:00.0': {
            'drivers': ['amdgpu'],
            'error': None,
        }
    }

    device = GPUDevice(
        gpu_type="AMD",
        pci_address="0000:19:00.0",
        device_delegate=mock_device_delegate
    )

    xml_elements = device.xml(device_context)
    xml_str = ''.join(ET.tostring(elem, encoding='unicode') for elem in xml_elements)

    # Should use renderD128, not card1 or controlD65
    assert '/dev/dri/renderD128' in xml_str
    assert '/dev/dri/card1' not in xml_str
    assert '/dev/dri/controlD65' not in xml_str
