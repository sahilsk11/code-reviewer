from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BRAINTRUST_PROJECT = "Code Reviewer"


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
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        os.environ[name] = value


def braintrust_project() -> str:
    return os.environ.get("BRAINTRUST_PROJECT", DEFAULT_BRAINTRUST_PROJECT)
