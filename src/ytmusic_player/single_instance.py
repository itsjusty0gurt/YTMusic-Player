from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


class SingleInstanceLock:
    """Own a Qt lock file for the lifetime of one application process."""

    def __init__(self, path: Path) -> None:
        self._lock = QLockFile(str(path))
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        if self._acquired:
            return True
        self._acquired = self._lock.tryLock(0)
        return self._acquired

    def release(self) -> None:
        if self._acquired:
            self._lock.unlock()
            self._acquired = False
