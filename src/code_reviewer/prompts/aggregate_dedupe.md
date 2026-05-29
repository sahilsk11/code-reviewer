Aggregate the multi-agent review into the final publishable result.

Original review payload:
$ARGUMENTS

Prepared worktree:
$prepare_worktree.output

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
- Re-read prior comments, review threads, outdated flags, and replies from
  GitHub before finalizing. Treat the review brief as a starting point, not
  the final source of truth.
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
- End with exactly one fenced `json` block. The JSON object itself must be
  the publish payload. Do not wrap it in `publish_payload`, `payload`,
  `result`, or any other outer key.
- The JSON object must include `blocking_count`, `non_blocking_count`,
  `check_conclusion` (`success` or `failure`), and `findings` with stable
  ids and `blocking` booleans. Findings should include `source`
  (`new_finding` or `prior_active_comment`), `post_inline` boolean, and
  `prior_comment_url` when carrying forward an existing comment.
- Use this exact top-level shape:

  ```json
  {
    "blocking_count": 1,
    "non_blocking_count": 2,
    "check_conclusion": "failure",
    "findings": [
      {
        "id": "example-finding-id",
        "blocking": true,
        "source": "new_finding",
        "post_inline": true,
        "prior_comment_url": null
      }
    ]
  }
  ```
