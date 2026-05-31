# Integration

The repository no longer includes a GitHub Actions path for running AI reviews.
The bundled `.github/workflows/ci.yml` workflow is ordinary package CI: it runs
Ruff, Pyright, and pytest against this Python codebase. See
[GitHub App Setup](github-app.md) for the manifest, SAS secret contract, and the
deferred app-owned worker/check publisher path.

To run a review manually, check out the exact PR head commit and provide the PR
URL and head SHA:

```sh
code-review review \
  --repo /path/to/target/repo \
  --pr-url https://github.com/owner/repo/pull/123 \
  --head-sha HEAD_SHA
```

For manual runs, a PR URL is sufficient when GitHub CLI can resolve the PR:

```sh
code-review review --pr-url https://github.com/owner/repo/pull/123
```

Useful runner flags:

- `--repo`: repository checkout to review. Defaults to the current directory.
- `--pr-url`: pull request URL. Required.
- `--head-sha`: exact PR head SHA. Actions should pass this explicitly.
- `--mode`: review mode metadata, currently `incremental` or `full`.
- `--harness`: Archon provider/harness rendered into the generated workflow.
- `--model`: model rendered into the generated workflow's agent nodes.
- `--dry-run`: run without publishing GitHub comments or checks.

## Reviewer Controls

Controls are stable HTML comment tokens. They can be emitted with the CLI and
posted to the PR as comments:

```sh
code-review control pause --reason "waiting on human review"
code-review control resume
code-review control full
code-review control incremental
code-review control ignore --finding-id finding-123 --reason "false positive"
code-review control resolve --finding-id finding-123
```

The bundled Archon workflow is responsible for reading these controls and
applying them before publishing new comments. The future app-owned publisher
should own the final required check result.

## Dry Runs

Use `--dry-run` to exercise the full review workflow without publishing GitHub
comments or checks:

```sh
code-review review \
  --repo /path/to/target/repo \
  --pr-url https://github.com/owner/repo/pull/123 \
  --mode full \
  --dry-run
```

In dry-run mode, the publish node renders the summary comment, inline comments,
and blocking conclusion it would have sent to GitHub.

## Run State

`code-review review` records each run in `~/.code-reviews/runs.db`, including
repository, PR number, head SHA, mode, harness, model, workflow name, workflow
path, full generated workflow YAML, status, Archon run id when available, and
exit code.

Before a new run starts, the CLI looks for active code-reviewer runs for the
same repository and PR. If it can match one to an active Archon run, it calls
`archon workflow abandon <run-id>` and then verifies the run no longer appears
in `archon workflow status --json --cwd <repo>`. The old code-reviewer run is
then marked canceled and linked to the replacement run.

## Transcript Context

The workflow does not pass every matching transcript into the review. A
transcript-selection agent first runs the transcript helper, inspects the
candidate report and normalized files, and selects one canonical implementation
transcript when one is available. If no implementation transcript is obvious,
the review continues without transcript context.

## Dedupe Strategy

Each finding should have a stable ID derived from path, line, category, and the
core message. The workflow should include that ID in hidden comment metadata and
skip reposting when an unresolved comment for the same finding ID already
exists.

## Staleness Strategy

The workflow should mark older summary comments stale when their reviewed SHA
differs from the current `head_sha`.
