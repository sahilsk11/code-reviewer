# Integration

The current production integration is GitHub Actions. The GitHub App manifest
and SAS webhook queue are being introduced as a separate path; keep this
workflow installed and required until the app worker and app-owned check-run
publisher are complete. See [GitHub App Setup](github-app.md) for the manifest,
SAS secret contract, and deferred worker pieces.

1. Copy `.github/workflows/ai-code-review.yml` into the target repository.
2. Register a trusted self-hosted runner with the label `code-reviewer`.
3. Run the service as the `code-reviewer` Unix user. Ensure that user has
   Archon, Codex, and GitHub CLI on `PATH`, and Codex authenticated.
4. Update the `Install code-reviewer` step to use a pinned tag or internal package source.
5. Merge the workflow.
6. In branch protection, require the `AI Code Review` check.

The self-hosted runner job is gated to same-repository pull requests from
trusted authors. A separate GitHub-hosted `AI Code Review` job remains required
and fails when the runner job is skipped or unsuccessful, so branch protection
does not treat skipped self-hosted reviews as passing. The review uses the
runner user's local Codex authentication through Archon and exports
`CODEX_BIN_PATH` from the runner's `codex` binary before invoking the review.
The bundled Archon workflow grants Codex access to `/home/code-reviewer/wt` for
prepared review worktrees and `/home/code-reviewer/.kanna` for runner-user
transcripts.

The workflow checks out `github.event.pull_request.head.sha`, passes the PR URL,
and passes that exact SHA to `code-review review`. The reviewer must use that
SHA for all review and publishing decisions. The CLI builds a run-specific
Archon workflow before each invocation and stores run state in
`~/.code-reviews/runs.db`.

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
applying them before publishing new comments. The GitHub Actions job owns the
final check result through the reviewer process exit code.

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

The GitHub Actions concurrency group cancels in-progress runs for the same PR.
The workflow should also mark older summary comments stale when their reviewed
SHA differs from the current `head_sha`.
