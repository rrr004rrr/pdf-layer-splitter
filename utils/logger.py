"""Simple in-app logger that stores messages and notifies listeners."""

import datetime
from typing import Callable


class AppLogger:
    def __init__(self):
        self._entries: list[str] = []
        self._listeners: list[Callable[[str], None]] = []

    def add_listener(self, cb: Callable[[str], None]):
        self._listeners.append(cb)

    def remove_listener(self, cb: Callable[[str], None]):
        self._listeners.discard(cb) if hasattr(self._listeners, 'discard') else None

    def _write(self, level: str, msg: str):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        line = f"[{ts}] {level}: {msg}"
        self._entries.append(line)
        for cb in self._listeners:
            try:
                cb(line)
            except Exception:
                pass

    def info(self, msg: str):
        self._write('INFO', msg)

    def warning(self, msg: str):
        self._write('WARN', msg)

    def error(self, msg: str):
        self._write('ERROR', msg)

    def debug(self, msg: str):
        self._write('DEBUG', msg)

    def get_all(self) -> list[str]:
        return list(self._entries)


# Module-level default logger instance
logger = AppLogger()
