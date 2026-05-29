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

Run a review from GitHub Actions:

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

## GitHub Actions

Copy `.github/workflows/ai-code-review.yml` into a target repo and update the
package install source if needed.

The workflow targets a trusted self-hosted GitHub Actions runner labeled
`code-reviewer` and only runs for same-repository pull requests from trusted
authors. The required `AI Code Review` check is enforced by a separate
GitHub-hosted job so skipped self-hosted jobs cannot pass branch protection.
The runner service user is expected to be `code-reviewer`; Archon, Codex, and
GitHub CLI must be available on `PATH`, with Codex authenticated for that user.
The job exports
`CODEX_BIN_PATH` from the runner's `codex` binary for Archon, and installs
lightweight review tooling so reviewer agents can reproduce common Python
verification commands.

The required check should be named `AI Code Review`. Configure branch protection
to require that check once the workflow is installed in the target repository.

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
