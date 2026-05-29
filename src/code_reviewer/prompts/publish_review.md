Publish the final AI Code Review result to GitHub.

Original review payload:
$ARGUMENTS

Prepared worktree:
$prepare_worktree.output

Review brief:
$summarize_intent.output

Final deduped review:
$aggregate_dedupe.output

Requirements:
- If the original review payload has `dry_run: true`, do not create,
  update, or delete any GitHub comments or reviews. Produce the exact
  summary/comment payloads that would have been published.
- Do not create, update, or delete GitHub check runs or commit statuses.
  The GitHub Actions job owns the required check result. The deterministic
  `cleanup_worktree` node will fail the job when blocking findings remain.
- Use the GitHub CLI/API from the prepared worktree.
- Update one stable PR summary comment identified by a hidden
  `code-review:summary` marker.
- Include reviewed SHA, review mode, status, blocking count, non-blocking
  count, and skipped/deduped count.
- Post high-confidence inline comments from the final finding list.
- Do not post a duplicate inline comment for findings whose
  `post_inline` is false because an active unresolved comment already
  exists.
- Include carried-forward active blockers in the summary
  even when no new inline comment is posted for them.
- Include hidden stable finding metadata in posted inline comments.
- Mark older summary comments stale when they refer to older SHAs.
- Avoid reposting duplicate inline comments.
- If GitHub publishing fails, diagnose and fix ordinary scripting/API
  mistakes, then retry once. If credentials or permissions are missing,
  report the exact blocker.

Output:
- Summary comment URL or publishing blocker.
- Inline comments posted, skipped as duplicates, or suppressed by controls.
- Final blocking conclusion and reason that the deterministic cleanup node
  will enforce through the Actions job exit code.
- In dry-run mode, the would-be summary comment body, inline comments, and
  blocking conclusion instead of GitHub URLs.
