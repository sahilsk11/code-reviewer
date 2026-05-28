from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from braintrust import Eval, Score

PROJECT_NAME = "My Project"
EXAMPLES_DIR = Path(__file__).parent / "examples"

DEFAULT_CASES = {
    "hello_world.py": {
        "must_include": ["no issue"],
        "must_not_include": ["typo", "bug"],
    },
    "hello_world_typo.py": {
        "must_include": ["typo", "helo"],
        "must_not_include": [],
    },
    "hello_world_bug.py": {
        "must_include": ["nameerror", "message"],
        "must_not_include": [],
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tiny Braintrust eval for Codex code review.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files to review. Defaults to evals/examples/*.py.",
    )
    parser.add_argument("--model", default=os.environ.get("CODEX_EVAL_MODEL"))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)

    if not os.environ.get("BRAINTRUST_API_KEY"):
        raise SystemExit("BRAINTRUST_API_KEY is required to run this eval.")

    paths = args.paths or sorted(EXAMPLES_DIR.glob("*.py"))
    if not paths:
        raise SystemExit("No eval files found.")

    result = Eval(
        PROJECT_NAME,
        experiment_name="code-review-v0",
        data=[case_for_path(path) for path in paths],
        task=lambda input: review_file(input, model=args.model, timeout=args.timeout),
        scores=[three_bullets, concise_output, expected_signal],
        metadata={"runner": "evals/code_review_v0.py", "model": args.model or "codex-default"},
        max_concurrency=1,
    )
    print(result.summary)
    return 0


def case_for_path(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    expected = DEFAULT_CASES.get(resolved.name, {"must_include": [], "must_not_include": []})
    return {
        "input": {
            "path": str(resolved),
            "name": resolved.name,
            "code": resolved.read_text(encoding="utf-8"),
        },
        "expected": expected,
        "metadata": {"case": resolved.stem},
    }


def review_file(input: dict[str, Any], *, model: str | None, timeout: int) -> str:
    prompt = f"""Review this tiny Python file.
Return exactly three markdown bullet points.
Keep each bullet under 12 words.
Mention concrete typo or bug signals if present.
If the file is fine, say "no issue" in one bullet.

File: {input["name"]}

```python
{input["code"]}
```
"""
    with tempfile.NamedTemporaryFile(prefix="code-review-v0-", suffix=".md") as output_file:
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-last-message",
            output_file.name,
        ]
        if model:
            command.extend(["--model", model])
        command.append("-")

        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        output = Path(output_file.name).read_text(encoding="utf-8").strip()
        if completed.returncode != 0:
            return (
                "- codex command failed\n"
                f"- exit code {completed.returncode}\n"
                f"- {completed.stderr.strip()[:160]}"
            )
        return output


def three_bullets(input: dict[str, Any], output: str, expected: dict[str, Any]) -> Score:
    bullets = bullet_lines(output)
    return Score(
        name="three_bullets",
        score=1.0 if len(bullets) == 3 else 0.0,
        metadata={"bullet_count": len(bullets)},
    )


def concise_output(input: dict[str, Any], output: str, expected: dict[str, Any]) -> Score:
    bullets = bullet_lines(output)
    if not bullets:
        return Score(name="concise_output", score=0.0)
    longest = max(len(line.removeprefix("- ").split()) for line in bullets)
    return Score(
        name="concise_output",
        score=1.0 if len(output) <= 360 and longest <= 12 else 0.0,
        metadata={"chars": len(output), "longest_bullet_words": longest},
    )


def expected_signal(input: dict[str, Any], output: str, expected: dict[str, Any]) -> Score:
    normalized = output.lower()
    must_include = [term.lower() for term in expected.get("must_include", [])]
    must_not_include = [term.lower() for term in expected.get("must_not_include", [])]
    included = [term for term in must_include if term in normalized]
    forbidden = [term for term in must_not_include if term in normalized]
    total = len(must_include) + len(must_not_include)
    passed = len(included) + (len(must_not_include) - len(forbidden))
    return Score(
        name="expected_signal",
        score=1.0 if total == 0 else passed / total,
        metadata={"included": included, "forbidden": forbidden},
    )


def bullet_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip().startswith("- ")]


if __name__ == "__main__":
    sys.exit(main())
