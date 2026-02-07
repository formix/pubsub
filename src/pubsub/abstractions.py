"""Directory utilities for pubsub library."""

import os
import sys
import tempfile
from pathlib import Path


# Cache for the base directory to avoid repeated lookups
_base_dir_cache = None


def get_base_dir() -> Path:
    """
    Get the base directory for pubsub storage that works across platforms.
    
    First checks for the PUBSUB_HOME environment variable. If not set,
    uses the system's temporary directory with a 'pubsub' subdirectory.
    On Unix-like systems, prefers /dev/shm if available for better performance.
    
    The result is cached after the first call for performance.
    
    Returns:
        Path: The base directory path for pubsub storage
    """
    global _base_dir_cache
    if _base_dir_cache is not None:
        return _base_dir_cache
    
    env_dir = os.environ.get("PUBSUB_HOME")
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


def is_process_running(pid: int) -> bool:
    """
    Check if a process with the given PID is currently running.
    
    Works across different operating systems:
    - Unix-like (Linux, macOS, BSD): Uses os.kill(pid, 0) to check existence
    - Windows: Checks if the process directory exists in /proc or uses ctypes
    
    Args:
        pid: The process ID to check
        
    Returns:
        True if the process is running, False otherwise
    """
    if pid <= 0:
        return False
    
    try:
        if sys.platform != "win32":
            # Unix-like systems: Use os.kill with signal 0
            # Signal 0 doesn't send a signal but checks if the process exists
            os.kill(pid, 0)
            return True
        else:
            # Windows: Try to open the process handle
            import ctypes
            PROCESS_QUERY_INFORMATION = 0x0400
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
    except (OSError, ProcessLookupError, AttributeError):
        # OSError/ProcessLookupError: Process doesn't exist
        # AttributeError: ctypes not available or other import issues
        return False

