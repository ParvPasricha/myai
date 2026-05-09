"""
Structured JSON logger for PARV-AI.

Usage:
    from observability.logger import log
    log.info("llm_response", service="llm_router", latency_ms=342, model="llama3.2")
    log.error("mqtt_disconnect", service="server", error="Connection refused")
"""
import json
import logging
import time
from pathlib import Path
from typing import Any

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

# File handler — one rolling log file
_file_handler = logging.FileHandler(_LOG_DIR / "parv_ai.jsonl")
_file_handler.setFormatter(logging.Formatter("%(message)s"))

# Console handler — human readable in dev
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter("%(message)s"))

_root = logging.getLogger("parv_ai")
_root.setLevel(logging.DEBUG)
_root.addHandler(_file_handler)
_root.addHandler(_console_handler)
_root.propagate = False


class _StructuredLogger:
    def _emit(self, level: str, event: str, **fields: Any):
        entry = {
            "ts": time.time(),
            "level": level,
            "event": event,
            **fields,
        }
        line = json.dumps(entry)
        if level == "error":
            _root.error(line)
        elif level == "warn":
            _root.warning(line)
        elif level == "debug":
            _root.debug(line)
        else:
            _root.info(line)

    def info(self, event: str, **fields: Any):
        self._emit("info", event, **fields)

    def warn(self, event: str, **fields: Any):
        self._emit("warn", event, **fields)

    def error(self, event: str, **fields: Any):
        self._emit("error", event, **fields)

    def debug(self, event: str, **fields: Any):
        self._emit("debug", event, **fields)


log = _StructuredLogger()
