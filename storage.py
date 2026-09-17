"""Fail-closed JSON persistence. Corrupt state is never replaced with empty data."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path


class StateError(RuntimeError):
    pass


def load_json(path: Path, default):
    if not path.exists():
        return copy.deepcopy(default)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise StateError(f"Arşiv okunamıyor; dosya korunuyor: {path.name}") from exc
    if not isinstance(value, type(default)):
        raise StateError(f"Arşiv şeması geçersiz: {path.name}")
    return value


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
