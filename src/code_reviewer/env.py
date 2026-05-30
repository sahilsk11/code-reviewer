from __future__ import annotations

import os
from pathlib import Path


def load_local_env(start: Path | None = None) -> None:
    """Load a local .env file without overriding the process environment."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        env_path = directory / ".env"
        if env_path.exists():
            load_env_file(env_path)
            return


def load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[name] = value
