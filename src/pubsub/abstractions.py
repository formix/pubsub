"""Directory utilities for pubsub library."""

import os
import platform
from pathlib import Path


# Cache for the base directory to avoid repeated lookups
_base_dir_cache = None


def get_base_dir() -> Path:
    """
    Get the base directory for pubsub storage that works across platforms.
    
    First checks for the PUBSUB_BASE_DIR environment variable. If not set,
    selects the most appropriate directory based on the operating system:
    - Windows: %TEMP%/pubsub (user's temp directory)
    - Unix-like (Linux/macOS/BSD): /dev/shm/pubsub if available (shared memory),
      otherwise /tmp/pubsub
    
    The result is cached after the first call for performance.
    
    Returns:
        Path: The base directory path for pubsub storage
    """
    global _base_dir_cache
    if _base_dir_cache is not None:
        return _base_dir_cache
    
    env_dir = os.environ.get("PUBSUB_BASE_DIR")
    if env_dir:
        _base_dir_cache = Path(env_dir)
        return _base_dir_cache
    
    system = platform.system()
    if system == "Windows":
        temp_dir = os.environ.get("TEMP", os.environ.get("TMP", "C:\\Temp"))
        base_dir = Path(temp_dir) / "pubsub"
    else:
        # Unix-like systems (Linux, macOS, BSD, etc.)
        # Prefer shared memory for best performance, if available
        shm_path = Path("/dev/shm")
        if shm_path.exists() and shm_path.is_dir():
            base_dir = shm_path / "pubsub"
        else:
            base_dir = Path("/tmp/pubsub")
    
    _base_dir_cache = base_dir
    return base_dir
