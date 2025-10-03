import functools
import os


@functools.cache
def kvm_supported() -> bool:
    """
    Check if KVM is supported on this system.
    """
    return os.path.exists('/dev/kvm')
