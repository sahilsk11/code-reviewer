from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from code_reviewer.commands.common import read_json, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove a managed code-review worktree.")
    parser.add_argument("--worktree-manifest", required=True)
    args = parser.parse_args(argv)

    manifest_path = Path(strip_wrapping_quotes(args.worktree_manifest)).expanduser()
    manifest = read_json(manifest_path)
    if manifest.get("managed_by") != "code-reviewer":
        raise SystemExit(f"Refusing to clean unmanaged worktree manifest: {manifest_path}")

    worktree_path = Path(str(manifest["worktree_path"])).expanduser().resolve()
    source_repo = Path(str(manifest["source_repo"])).expanduser().resolve()
    if not is_under(worktree_path, Path.home() / "wt"):
        raise SystemExit(f"Refusing to clean worktree outside ~/wt: {worktree_path}")

    run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=source_repo, check=False)
    if worktree_path.exists():
        shutil.rmtree(worktree_path)
    run(["git", "worktree", "prune"], cwd=source_repo, check=False)
    print(f"removed {worktree_path}")
    return 0


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.expanduser().resolve())
    except ValueError:
        return False
    return True


def strip_wrapping_quotes(value: str) -> str:
    text = value.strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


if __name__ == "__main__":
    sys.exit(main())
