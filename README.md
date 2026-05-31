# code-reviewer

Python CLI wrapper for an Archon-powered pull request reviewer.

The Python package builds the Archon workflow at runtime from prompt resources
and run configuration, records review run state in SQLite, and invokes Archon.
The review logic, GitHub comments, deduplication, stale-run handling, and
blocking-finding decisions still live in the generated workflow.

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

Run a review from an exact checked-out PR head:

```sh
code-review review \
  --repo . \
  --pr-url "$PR_URL" \
  --head-sha "$PR_HEAD_SHA"
```

Run a review manually:

```sh
code-review review \
  --pr-url https://github.com/owner/repo/pull/123
```

The PR URL is enough for manual runs when GitHub CLI can resolve the head SHA.
Actions should still pass `--head-sha` to pin the review to the checked-out
commit. `--repo` defaults to the current directory.

Run without publishing comments or checks:

```sh
code-review review \
  --repo /path/to/target/repo \
  --pr-url https://github.com/owner/repo/pull/123 \
  --mode full \
  --dry-run
```

Select a workflow harness/provider or model for a run:

```sh
code-review review \
  --pr-url https://github.com/owner/repo/pull/123 \
  --harness opencode \
  --model opencode-go/deepseek-v4-pro
```

`--mode incremental|full` is currently passed through to the workflow payload so
prompts and reviewer controls can distinguish normal and full reviews. It does
not change the Python runner behavior.

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

Generate a GitHub App manifest for the future SAS-backed webhook path:

```sh
code-review github-app manifest \
  --webhook-url https://sas.example.com/github-code-review-app
```

The manifest is documented in [docs/github-app.md](docs/github-app.md). The
repository CI does not run AI reviews; it only verifies the Python codebase.

## GitHub Actions

The bundled `.github/workflows/ci.yml` workflow verifies this Python package on
pull requests and pushes to `main`. It runs Ruff, Pyright, and pytest on a
GitHub-hosted runner. It does not invoke `code-review review`, Archon, Codex, or
the self-hosted AI review runner.

Configure branch protection against the `Python Checks` job if this repository
needs a required CI check.

## Workflow And State

The generated workflow is assembled from `src/code_reviewer/workflow_builder.py`
and prompt files in `src/code_reviewer/prompts/`. `install-workflow` writes the
default generated workflow to `.archon/workflows/ai-code-review.yaml`. Each
review run writes a run-specific workflow such as
`.archon/workflows/ai-code-review-<id>.yaml` before invoking Archon.

Run state is stored in `~/.code-reviews/runs.db`. The CLI records repository,
PR number, head SHA, mode, harness, model, generated workflow name/path/YAML,
status, Archon run id when observed, and exit code. Before starting a new run,
the CLI looks for active code-reviewer runs for the same repository and PR,
abandons the matching Archon run when it can identify one, verifies the run is
gone from `archon workflow status`, then marks the old run canceled.

Deterministic workflow steps are Python command modules:

```text
code_reviewer.commands.prepare_worktree
code_reviewer.commands.collect_github_context
code_reviewer.commands.discover_transcripts
code_reviewer.commands.publish_review
code_reviewer.commands.cleanup_worktree
```

`discover_transcripts` is a helper for the transcript-selection agent: it writes
a readable candidate report plus normalized transcript files. GitHub reads and
writes are owned by deterministic Python steps: `collect_github_context` gathers
PR comments, review comments, reviews, and files before agent review, while
`publish_review` parses the aggregate output and posts the resulting top-level
or inline comments. Agent nodes handle canonical transcript selection, intent
summarization, parallel review, and aggregation; they should not call GitHub
directly.

## Verification

```sh
make checks
python -m ruff check .
python -m pyright
python -m pytest
```
