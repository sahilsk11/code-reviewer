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

If that succeeds, post a comment shaped like:

````markdown
## Braintrust evals

Command:
`<exact command>`

Experiment:
<Braintrust URL, or "not found in output">

Summary:

```text
<score summary>
```
````

Use:

```sh
gh pr comment "$PR_NUMBER" --body-file /tmp/code-reviewer-evals-comment.md
```

One straightforward way to create the comment file is:

```sh
{
  printf '## Braintrust evals\n\n'
  printf 'Command:\n`%s`\n\n' "$EVAL_COMMAND"
  printf 'Experiment:\n%s\n\n' "${BRAINTRUST_URL:-not found in output}"
  printf 'Summary:\n\n```text\n'
  sed -n '/SUMMARY/,$p' /tmp/code-reviewer-evals.log
  printf '\n```\n'
} > /tmp/code-reviewer-evals-comment.md
```

If no open pull request exists for the current branch, do not create a PR just for eval output. Report the command, experiment URL, and summary to the user instead.

## Notes

- Do not run evals from the primary checkout if the user asked to keep it untouched; use the active worktree.
- Do not include secrets or full `.env` contents in comments or user-visible output.
- The current eval suite is intentionally small and scorer quality is still evolving. Treat results as review context unless the user explicitly asks to use them as a merge gate.
