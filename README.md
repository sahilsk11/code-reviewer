# code-reviewer

Thin Python CLI wrapper for an Archon-powered pull request reviewer.

The Python package intentionally stays small. It installs and runs a bundled
Archon workflow named `ai-code-review`; the review logic, GitHub comments,
deduplication, stale-run handling, and blocking-finding decisions live in that
workflow.

## Install for development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Archon must be installed and available on `PATH`:

```sh
archon doctor
```

## CLI

Install the bundled workflow into the current repo:

```sh
code-review install-workflow
```

Run a review from a GitHub Actions pull request event:

```sh
code-review review \
  --repo . \
  --event-path "$GITHUB_EVENT_PATH" \
  --head-sha "$PR_HEAD_SHA"
```

Run a review manually:

```sh
code-review review \
  --repo /path/to/target/repo \
  --pr-url https://github.com/owner/repo/pull/123
```

Run without publishing comments or checks:

```sh
code-review review \
  --repo /path/to/target/repo \
  --pr-url https://github.com/owner/repo/pull/123 \
  --mode full \
  --dry-run
```

Reviewer controls emit stable tokens that the workflow can read from PR
comments or operator logs:

```sh
code-review control pause --reason "manual inspection"
code-review control resume
code-review control full
code-review control incremental
code-review control ignore --finding-id finding-123
code-review control resolve --finding-id finding-123
```

## GitHub Actions

Copy `.github/workflows/ai-code-review.yml` into a target repo and update the
package install source if needed.

The required check should be named `AI Code Review`. Configure branch protection
to require that check once the workflow is installed in the target repository.

## Workflow

The shipped workflow lives at `src/code_reviewer/workflows/ai-code-review.yaml`.
The `.archon/workflows/ai-code-review.yaml` copy is kept in this repository so
Archon can discover and preview the workflow locally.

Deterministic workflow steps are Python command modules:

```text
code_reviewer.commands.prepare_worktree
code_reviewer.commands.discover_transcripts
code_reviewer.commands.cleanup_worktree
```

`discover_transcripts` is a helper for the transcript-selection agent: it writes
a readable candidate report plus normalized transcript files. Agent nodes handle
canonical transcript selection, intent summarization, parallel review,
aggregation, and publishing.

## Verification

```sh
python -m pytest
python -m compileall src
```
