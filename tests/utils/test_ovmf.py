from unittest.mock import patch

import pytest

from truenas_pylibvirt.utils.ovmf import get_ovmf_vars_file


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the function cache before each test."""
    get_ovmf_vars_file.cache_clear()
    yield
    get_ovmf_vars_file.cache_clear()


def mock_exists_factory(existing_files: set[str]):
    """Create a mock os.path.exists that returns True for files in existing_files."""
    def mock_exists(path: str) -> bool:
        return path in existing_files
    return mock_exists


@pytest.mark.parametrize('code_filename,existing_files,expected', [
    # Basic CODE -> VARS matching
    (
        'OVMF_CODE.fd',
        {'/usr/share/OVMF/OVMF_VARS.fd'},
        '/usr/share/OVMF/OVMF_VARS.fd',
    ),
    # Secboot CODE -> ms VARS
    (
        'OVMF_CODE.secboot.fd',
        {'/usr/share/OVMF/OVMF_VARS.fd', '/usr/share/OVMF/OVMF_VARS.ms.fd'},
        '/usr/share/OVMF/OVMF_VARS.ms.fd',
    ),
    # ms CODE -> ms VARS
    (
        'OVMF_CODE.ms.fd',
        {'/usr/share/OVMF/OVMF_VARS.fd', '/usr/share/OVMF/OVMF_VARS.ms.fd'},
        '/usr/share/OVMF/OVMF_VARS.ms.fd',
    ),
    # 4M basic CODE -> 4M VARS
    (
        'OVMF_CODE_4M.fd',
        {'/usr/share/OVMF/OVMF_VARS_4M.fd'},
        '/usr/share/OVMF/OVMF_VARS_4M.fd',
    ),
    # 4M secboot CODE -> 4M ms VARS
    (
        'OVMF_CODE_4M.secboot.fd',
        {'/usr/share/OVMF/OVMF_VARS_4M.fd', '/usr/share/OVMF/OVMF_VARS_4M.ms.fd'},
        '/usr/share/OVMF/OVMF_VARS_4M.ms.fd',
    ),
    # 4M secboot strictnx CODE -> 4M ms VARS
    (
        'OVMF_CODE_4M.secboot.strictnx.fd',
        {'/usr/share/OVMF/OVMF_VARS_4M.fd', '/usr/share/OVMF/OVMF_VARS_4M.ms.fd'},
        '/usr/share/OVMF/OVMF_VARS_4M.ms.fd',
    ),
    # 4M snakeoil CODE -> 4M snakeoil VARS
    (
        'OVMF_CODE_4M.snakeoil.fd',
        {
            '/usr/share/OVMF/OVMF_VARS_4M.fd',
            '/usr/share/OVMF/OVMF_VARS_4M.ms.fd',
            '/usr/share/OVMF/OVMF_VARS_4M.snakeoil.fd',
        },
        '/usr/share/OVMF/OVMF_VARS_4M.snakeoil.fd',
    ),
    # Snakeoil fallback to ms when snakeoil VARS missing
    (
        'OVMF_CODE_4M.snakeoil.fd',
        {'/usr/share/OVMF/OVMF_VARS_4M.fd', '/usr/share/OVMF/OVMF_VARS_4M.ms.fd'},
        '/usr/share/OVMF/OVMF_VARS_4M.ms.fd',
    ),
    # Secboot fallback to basic when ms VARS missing
    (
        'OVMF_CODE.secboot.fd',
        {'/usr/share/OVMF/OVMF_VARS.fd'},
        '/usr/share/OVMF/OVMF_VARS.fd',
    ),
    # Full path input
    (
        '/usr/share/OVMF/OVMF_CODE.secboot.fd',
        {'/usr/share/OVMF/OVMF_VARS.ms.fd'},
        '/usr/share/OVMF/OVMF_VARS.ms.fd',
    ),
    # 2M size variant
    (
        'OVMF_CODE_2M.fd',
        {'/usr/share/OVMF/OVMF_VARS_2M.fd'},
        '/usr/share/OVMF/OVMF_VARS_2M.fd',
    ),
    # No matching VARS returns None
    (
        'OVMF_CODE.fd',
        set(),
        None,
    ),
    # AAVMF: plain CODE -> plain VARS
    (
        'AAVMF_CODE.fd',
        {'/usr/share/AAVMF/AAVMF_VARS.fd'},
        '/usr/share/AAVMF/AAVMF_VARS.fd',
    ),
    # AAVMF: no-secboot CODE -> plain VARS (the "no-" must not trip secboot detection)
    (
        'AAVMF_CODE.no-secboot.fd',
        {'/usr/share/AAVMF/AAVMF_VARS.fd'},
        '/usr/share/AAVMF/AAVMF_VARS.fd',
    ),
    # AAVMF: ms CODE -> ms VARS
    (
        'AAVMF_CODE.ms.fd',
        {'/usr/share/AAVMF/AAVMF_VARS.fd', '/usr/share/AAVMF/AAVMF_VARS.ms.fd'},
        '/usr/share/AAVMF/AAVMF_VARS.ms.fd',
    ),
    # AAVMF: secboot CODE -> ms VARS
    (
        'AAVMF_CODE.secboot.fd',
        {'/usr/share/AAVMF/AAVMF_VARS.fd', '/usr/share/AAVMF/AAVMF_VARS.ms.fd'},
        '/usr/share/AAVMF/AAVMF_VARS.ms.fd',
    ),
    # AAVMF: secboot.strictnx CODE -> ms VARS
    (
        'AAVMF_CODE.secboot.strictnx.fd',
        {'/usr/share/AAVMF/AAVMF_VARS.fd', '/usr/share/AAVMF/AAVMF_VARS.ms.fd'},
        '/usr/share/AAVMF/AAVMF_VARS.ms.fd',
    ),
    # AAVMF: snakeoil CODE -> snakeoil VARS
    (
        'AAVMF_CODE.snakeoil.fd',
        {
            '/usr/share/AAVMF/AAVMF_VARS.fd',
            '/usr/share/AAVMF/AAVMF_VARS.ms.fd',
            '/usr/share/AAVMF/AAVMF_VARS.snakeoil.fd',
        },
        '/usr/share/AAVMF/AAVMF_VARS.snakeoil.fd',
    ),
    # AAVMF: snakeoil fallback to ms when snakeoil VARS missing
    (
        'AAVMF_CODE.snakeoil.fd',
        {'/usr/share/AAVMF/AAVMF_VARS.fd', '/usr/share/AAVMF/AAVMF_VARS.ms.fd'},
        '/usr/share/AAVMF/AAVMF_VARS.ms.fd',
    ),
    # AAVMF: secboot fallback to plain when ms VARS missing
    (
        'AAVMF_CODE.secboot.fd',
        {'/usr/share/AAVMF/AAVMF_VARS.fd'},
        '/usr/share/AAVMF/AAVMF_VARS.fd',
    ),
    # Invalid filename returns None
    (
        'some_other_file.fd',
        {'/usr/share/OVMF/OVMF_VARS.fd'},
        None,
    ),
])
def test_get_ovmf_vars_file(code_filename, existing_files, expected):
    with patch(
        'truenas_pylibvirt.utils.ovmf.os.path.exists',
        mock_exists_factory(existing_files)
    ):
        assert get_ovmf_vars_file(code_filename) == expected


def test_get_ovmf_vars_file_custom_dir():
    """Test with custom ovmf_dir parameter."""
    existing = {'/custom/path/OVMF_VARS.fd'}
    with patch(
        'truenas_pylibvirt.utils.ovmf.os.path.exists',
        mock_exists_factory(existing)
    ):
        result = get_ovmf_vars_file('OVMF_CODE.fd', ovmf_dir='/custom/path')
        assert result == '/custom/path/OVMF_VARS.fd'
