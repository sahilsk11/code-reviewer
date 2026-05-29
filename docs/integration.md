# Integration

1. Copy `.github/workflows/ai-code-review.yml` into the target repository.
2. Update the `Install Archon` step to use the organization's pinned Archon install source.
3. Update the `Install code-reviewer` step to use a pinned tag or internal package source.
4. Add an `OPENCODE_API_KEY` repository or organization secret for review runs.
5. Merge the workflow.
6. In branch protection, require the `AI Code Review` check.

The workflow writes the OpenCode API key into
`~/.local/share/opencode/auth.json` before running Archon.

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
