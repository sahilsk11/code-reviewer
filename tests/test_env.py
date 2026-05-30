from __future__ import annotations

import os
from pathlib import Path

from code_reviewer.env import braintrust_project, load_env_file, load_local_env


def test_load_env_file_reads_values_and_preserves_existing_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# comment",
                "FOO=bar",
                'QUOTED="two words"',
                "export EXPORTED=value",
                "INLINE=token # local note",
                "EXISTING=from-file",
                "NO_EQUALS",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.delenv("EXPORTED", raising=False)
    monkeypatch.delenv("INLINE", raising=False)
    monkeypatch.setenv("EXISTING", "from-env")

    load_env_file(env_path)

    assert os.environ["FOO"] == "bar"
    assert os.environ["QUOTED"] == "two words"
    assert os.environ["EXPORTED"] == "value"
    assert os.environ["INLINE"] == "token"
    assert os.environ["EXISTING"] == "from-env"


def test_load_local_env_walks_up_from_start_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("WALKED=1\n", encoding="utf-8")
    child = tmp_path / "nested" / "child"
    child.mkdir(parents=True)
    monkeypatch.delenv("WALKED", raising=False)

    load_local_env(child)

    assert os.environ["WALKED"] == "1"


def test_braintrust_project_uses_env_or_default(monkeypatch) -> None:
    monkeypatch.delenv("BRAINTRUST_PROJECT", raising=False)
    assert braintrust_project() == "Code Reviewer"

    monkeypatch.setenv("BRAINTRUST_PROJECT", "Custom Project")
    assert braintrust_project() == "Custom Project"
