Aggregate the multi-agent review into the final publishable result.

Original review payload:
$ARGUMENTS

Prepared worktree:
$prepare_worktree.output

Collected GitHub context:
$collect_github_context.output

Review brief:
$summarize_intent.output

Correctness/regressions reviewer:
$reviewer_correctness_regressions.output

Design/layering/reuse reviewer:
$reviewer_design_layering_reuse.output

Simplicity/alternatives reviewer:
$reviewer_simplicity_alternatives.output

Requirements:
- Deduplicate findings across reviewers by root cause, not only by line.
- Use the collected GitHub context for prior comments, review threads,
  outdated flags, replies, and controls. Do not call `gh`, the GitHub API, or
  network tools from this node.
- Suppress duplicate findings already posted as active unresolved comments
  for the current head/diff. Include them in skipped findings with reason
  `already_active_unresolved`.
- Do not suppress a fresh finding because the only matching prior comment
  is outdated.
- Treat active unresolved prior blocking AI comments as still blocking when
  no human replied and the current code does not clearly fix the issue.
  Carry them forward in the check result even if no new inline comment will
  be posted.
- Treat human replies as authoritative product feedback by default. If a
  human disagreed, explained why the issue is acceptable, or used an
  ignore/resolve control, suppress the repeated finding unless the current
  code has new concrete evidence or a new regression.
- If a human replied "fixed" but the current code still has the same issue,
  keep or recreate the finding as blocking and explain that the fix appears
  incomplete.
- Preserve blocking findings only when they should fail the required check:
  new blocking findings plus active unresolved carried-forward blocking
  findings.
- Drop unit-test-only complaints unless they identify the most useful
  verification for a concrete behavioral risk.
- Keep useful design tradeoffs in the summary when they are not actionable
  enough for inline comments.
- Prefer fewer, clearer inline comments over broad summaries.
- Produce readable Markdown with summary, final findings, skipped findings,
  active prior blockers carried forward, stale-comment actions, and check
  conclusion.
- End with exactly one fenced `json` block. The publisher will parse,
  validate, and normalize this block before posting to GitHub.
- The JSON object must include a `comments` list. Each comment must be either
  `inline` for a specific diff location or `top_level` for a general PR
  comment. Inline comments must include `path`, `line`, and `body`.
- Include `blocking: true` on comments that should fail the review.
- Use this top-level shape:

  ```json
  {
    "comments": [
      {
        "type": "inline",
        "path": "src/example.py",
        "line": 42,
        "body": "This path now skips the required permission check.",
        "blocking": true,
        "source": "new_finding"
      },
      {
        "type": "top_level",
        "body": "Summary-only note for the PR.",
        "blocking": false
      }
    ]
  }
  ```
