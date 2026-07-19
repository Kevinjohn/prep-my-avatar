"""Compatibility import for code that resolves the launcher lock via ``app``."""

from process_lock import AlreadyRunning, acquire

__all__ = ['AlreadyRunning', 'acquire']
