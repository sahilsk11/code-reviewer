# Integration

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

The workflow checks out `github.event.pull_request.head.sha` and passes that SHA
to `code-review review`. The reviewer must use that exact SHA for all review and
publishing decisions.

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
