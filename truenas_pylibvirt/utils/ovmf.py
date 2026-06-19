import functools
import os
import re


OVMF_DIR = '/usr/share/OVMF'
AAVMF_DIR = '/usr/share/AAVMF'


@functools.cache
def get_ovmf_vars_file(code_filename: str, ovmf_dir: str = OVMF_DIR) -> str | None:
    """
    Given an OVMF or AAVMF CODE filename, return the matching VARS file path.

    Prefix selects the firmware family:
    - OVMF_CODE*  -> ovmf_dir + OVMF_VARS  (x86)
    - AAVMF_CODE* -> AAVMF_DIR + AAVMF_VARS (aarch64)

    Matching also handles:
    - Size variant (e.g., _4M must match -- AAVMF has no size variants)
    - Secure boot support (secboot/ms CODE files get .ms VARS)
    - Special variants like snakeoil get their matching VARS

    Args:
        code_filename: The CODE filename (e.g., 'OVMF_CODE.secboot.fd' or
                       'AAVMF_CODE.ms.fd')
        ovmf_dir: Directory containing OVMF files (default: /usr/share/OVMF).
                  Ignored for AAVMF inputs which always use AAVMF_DIR.

    Returns:
        Full path to matching VARS file, or None if no match found
    """
    basename = os.path.basename(code_filename)

    if basename.startswith('OVMF_CODE'):
        vars_prefix = 'OVMF_VARS'
        vars_dir = ovmf_dir
    elif basename.startswith('AAVMF_CODE'):
        vars_prefix = 'AAVMF_VARS'
        vars_dir = AAVMF_DIR
    else:
        return None

    # Extract size variant (e.g., '_4M' for OVMF; AAVMF has none)
    size_match = re.search(r'(_\d+M)', basename)
    size_variant = size_match.group(1) if size_match else ''

    # Check for secure boot indicators
    is_secboot = any(indicator in basename for indicator in ['.secboot', '.ms'])

    # Check for snakeoil (self-signed test keys)
    is_snakeoil = '.snakeoil' in basename

    # Build candidate VARS filenames in order of preference
    candidates = []

    if is_snakeoil:
        candidates.append(f'{vars_prefix}{size_variant}.snakeoil.fd')
        candidates.append(f'{vars_prefix}{size_variant}.ms.fd')
    elif is_secboot:
        candidates.append(f'{vars_prefix}{size_variant}.ms.fd')

    # Always add the basic variant as fallback
    candidates.append(f'{vars_prefix}{size_variant}.fd')

    # Find first existing candidate
    for candidate in candidates:
        candidate_path = os.path.join(vars_dir, candidate)
        if os.path.exists(candidate_path):
            return candidate_path

    return None
