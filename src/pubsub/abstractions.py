"""Directory utilities for pubsub library."""

import os
import tempfile
from pathlib import Path


# Cache for the base directory to avoid repeated lookups
_base_dir_cache = None


def get_base_dir() -> Path:
    """
    Get the base directory for pubsub storage that works across platforms.
    
    First checks for the PUBSUB_BASE_DIR environment variable. If not set,
    uses the system's temporary directory with a 'pubsub' subdirectory.
    On Unix-like systems, prefers /dev/shm if available for better performance.
    
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
    
    shm_path = Path("/dev/shm")
    if shm_path.exists() and shm_path.is_dir():
        temp_dir = shm_path
    else:
        temp_dir = Path(tempfile.gettempdir())
    
    # Append pubsub subdirectory
    _base_dir_cache = temp_dir / "pubsub"
    return _base_dir_cache
