"""Keep Windows Qt/TLS libraries paired with this Python instead of inherited tool DLLs."""
import os
import sys
from pathlib import Path
from importlib.machinery import PathFinder

_prepared = False
_dll_handles = []


def prepare_runtime():
    global _prepared
    if _prepared or os.name != 'nt': return
    # A desktop launched by another app inherits that app's PATH. Prefer our
    # Python's OpenSSL pair and our Qt/FFmpeg binaries before any foreign tools.
    candidates = [Path(sys.base_prefix)/'DLLs', Path(sys.base_prefix)]
    spec = PathFinder.find_spec('PySide6')
    if spec and spec.submodule_search_locations:
        candidates += [Path(path) for path in spec.submodule_search_locations]
    directories = [str(path.resolve()) for path in candidates if path.is_dir()]
    preferred = {os.path.normcase(path) for path in directories}
    inherited = [path for path in os.environ.get('PATH','').split(os.pathsep)
                 if path and os.path.normcase(os.path.abspath(path)) not in preferred]
    os.environ['PATH'] = os.pathsep.join(directories + inherited)
    if hasattr(os, 'add_dll_directory'):
        for directory in directories:
            _dll_handles.append(os.add_dll_directory(directory))
    # Load both members via CPython's own _ssl extension before Qt attempts a
    # dynamic TLS lookup; hashlib alone can otherwise load only libcrypto.
    import ssl
    _prepared = True

