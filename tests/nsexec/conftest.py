# The nsexec package imports the compiled _native extension at import time, so
# these tests need it built. On a plain source checkout it isn't, so skip them
# instead of failing collection; CI builds the extension (see unit_tests.yml).
collect_ignore_glob = []
try:
    import truenas_pylibvirt.nsexec._native  # noqa: F401
except ImportError:
    collect_ignore_glob = ["test_*.py"]
