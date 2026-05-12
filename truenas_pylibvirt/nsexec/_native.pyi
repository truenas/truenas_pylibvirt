"""Type stubs for the ``truenas_pylibvirt.nsexec._native`` C extension.

See ``_native.c`` for the authoritative implementation; the function
table is ``NsexecMethods`` and the module constants are registered in
``PyInit__native``.
"""

CLONE_NEWNS: int
CLONE_NEWUTS: int
CLONE_NEWIPC: int
CLONE_NEWUSER: int
CLONE_NEWPID: int
CLONE_NEWNET: int
CLONE_NEWCGROUP: int
CLONE_NEWTIME: int


def setns(fd: int, nstype: int) -> None: ...
def drop_bounding(cap: int) -> None: ...
def cap_from_name(name: str) -> int: ...
def cap_to_name(cap: int) -> str: ...
def cap_max_bits() -> int: ...
def cap_set_proc_from_text(text: str) -> None: ...
def enter_and_exec(
    user_fd: int,
    other_fds: list[int],
    drop_names: list[str],
    caps_text: str,
    argv: list[str],
) -> int: ...
