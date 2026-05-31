---
name: run-evals
description: Run this repository's Braintrust-backed reviewer evals, summarize the results, and post them to the current pull request when one exists.
compatibility: codex
---

# Run Evals

Use this skill when the user asks to run evals/evalds for this repository, attach eval results to a pull request, or report Braintrust eval performance.

This is a repository-level workflow. Do not use `skillify` or install a global/server-level skill for this.

## What It Does

Run the local Braintrust eval suite from the active checkout, capture the result summary and Braintrust experiment link, then:

- If the current branch has an open GitHub pull request, post the results as a PR comment.
- If there is no open pull request, report the results directly to the user.

The evals execute locally through this repository's Python code and Codex CLI setup. Braintrust stores the experiment result, but Braintrust does not run the reviewer agent remotely.

## Preconditions

- Run from the repository root.
- Ensure dependencies are installed in the local environment.
- Ensure `BRAINTRUST_API_KEY` is available, either in the shell or in `.env`.
- Ensure local Codex CLI auth works before treating a failed eval as a prompt regression.
- Use `gh` for pull request detection and PR comments.

## Commands

Prefer the repository virtualenv when it exists:

```sh
PYTHON=.venv/bin/python
test -x "$PYTHON" || PYTHON=python
```

Run the currently curated reviewer eval:

```sh
$PYTHON evals/reviewer_correctness_regressions.py 2>&1 | tee /tmp/code-reviewer-evals.log
```

If the user asks for a specific model or timeout, pass them through:

```sh
$PYTHON evals/reviewer_correctness_regressions.py --model "$MODEL" --timeout "$TIMEOUT" 2>&1 | tee /tmp/code-reviewer-evals.log
```

If the user asks to run cases in parallel, pass `--max-concurrency N` or set `CODEX_EVAL_MAX_CONCURRENCY=N`:

```sh
$PYTHON evals/reviewer_correctness_regressions.py --max-concurrency "$N" 2>&1 | tee /tmp/code-reviewer-evals.log
```

Default to `1` for reproducibility and to avoid surprise Codex/API pressure. Use small values like `2` or `3` first; each concurrent case starts its own repo checkout and `codex exec` run.

## Summarize Results

Extract the Braintrust experiment URL when present:

```sh
rg -o 'https://www\.braintrust\.dev/[^ ]+' /tmp/code-reviewer-evals.log | tail -n 1
```

Extract the score summary:

```sh
sed -n '/SUMMARY/,$p' /tmp/code-reviewer-evals.log
```

If the eval command exits nonzero, include the exit status and the relevant stderr tail. Do not post a passing-sounding comment for a failed eval.

## PR Comment

Detect whether the current branch has an open pull request:

```sh
gh pr view --json number,url
```

If that succeeds, post a concise Markdown report. Do not paste the raw Braintrust CLI summary and do not include the eval command for successful runs. GitHub comments should be readable at a glance.

For successful eval runs, use this shape:

````markdown
## Braintrust evals

[View experiment: `<experiment-name>`](<Braintrust URL>)
Compared against: `<baseline-experiment-name>`

| Score | Result | Delta | Changes |
| --- | ---: | ---: | --- |
| completed | 100.00% | +100.00% | 1 improvement, 0 regressions |
| output_present | 100.00% | +100.00% | 1 improvement, 0 regressions |
| known_issue_present | 50.00% | - | 0 improvements, 0 regressions |

Notes:
- `known_issue_present` measures whether each case output mentions the known issue terms defined by the fixture.
- Full traces, task outputs, and metadata are in Braintrust.
````

For failed eval runs, use this shape:

````markdown
## Braintrust evals failed

The local eval command exited with status `<exit-status>`.

Relevant output:

```text
<short stderr/stdout tail>
```
````

Use:

```sh
gh pr comment "$PR_NUMBER" --body-file /tmp/code-reviewer-evals-comment.md
```

One straightforward way to create the success comment file is:

```sh
$PYTHON - <<'PY'
from __future__ import annotations

import re
from pathlib import Path

log = Path("/tmp/code-reviewer-evals.log").read_text(encoding="utf-8")
url_match = re.findall(r"https://www\.braintrust\.dev/[^ \n]+", log)
url = url_match[-1] if url_match else ""
summary_match = re.search(
    r"(?s)=+SUMMARY=+\n(?P<head>.+? compared to .+?:)\n(?P<body>.+?)(?:\n\nSee results|\Z)",
    log,
)
if summary_match:
    head = summary_match.group("head")
    experiment, baseline = head.removesuffix(":").split(" compared to ", 1)
    body = summary_match.group("body")
else:
    experiment = "unknown"
    baseline = "unknown"
    body = ""

rows = []
for line in body.splitlines():
    match = re.match(
        r"\s*(?P<result>[0-9.]+%)\s+\((?P<delta>[^)]*)\)\s+'(?P<score>[^']+)'\s+score\s+\((?P<changes>[^)]*)\)",
        line,
    )
    if match:
        rows.append(match.groupdict())

priority = ["completed", "output_present", "known_issue_present"]
rows_by_score = {row["score"]: row for row in rows}
ordered_rows = [rows_by_score[name] for name in priority if name in rows_by_score]
ordered_rows.extend(row for row in rows if row["score"] not in priority)

lines = [
    "## Braintrust evals",
    "",
    f"[View experiment: `{experiment}`]({url})" if url else f"Experiment: `{experiment}`",
    f"Compared against: `{baseline}`",
    "",
    "| Score | Result | Delta | Changes |",
    "| --- | ---: | ---: | --- |",
]
for row in ordered_rows:
    lines.append(
        f"| `{row['score']}` | {row['result']} | {row['delta']} | {row['changes']} |"
    )
lines.extend(
    [
        "",
        "Notes:",
        "- `known_issue_present` measures whether each case output mentions the known issue terms defined by the fixture.",
        "- Full traces, task outputs, and metadata are in Braintrust.",
        "",
    ]
)
Path("/tmp/code-reviewer-evals-comment.md").write_text(
    "\n".join(lines), encoding="utf-8"
)
PY
```

If no open pull request exists for the current branch, do not create a PR just for eval output. Report the command, experiment URL, and summary to the user instead.

## Notes

- Do not run evals from the primary checkout if the user asked to keep it untouched; use the active worktree.
- Do not include secrets or full `.env` contents in comments or user-visible output.
- The current eval suite is intentionally small and scorer quality is still evolving. Treat results as review context unless the user explicitly asks to use them as a merge gate.
