Review this PR for correctness and regressions.

Original review payload:
$ARGUMENTS

Prepared worktree:
$prepare_worktree.output

Review brief:
$summarize_intent.output

Requirements:
- Review exactly the supplied head SHA, never a moving branch reference.
- Trace affected code paths beyond the diff when needed to understand the
  actual runtime behavior.
- Focus on concrete defects with high confidence: broken flows, edge cases,
  stale state, async/concurrency mistakes, data loss, permission mistakes,
  missing cleanup, and regressions to existing behavior.
- Evaluate whether the PR includes useful real verification for behavioral
  functionality, such as an end-to-end check, screenshot, browser exercise,
  API smoke test, or command output. Do not complain about missing unit tests
  unless that is the best practical verification for the risk.
- Respect prior human replies, ignore controls, and resolve controls from the brief.
- Do not repost active unresolved comments already present on the PR.
- Do not suppress a fresh finding because of an outdated prior comment.
- If a prior blocking AI comment is active, unresolved, and still broken,
  include it as a carried-forward blocking finding instead of dropping it.
- If a prior comment has a human reply, treat that reply as authoritative
  context unless the current code provides new, concrete evidence that the
  issue remains or has regressed.
- Output readable Markdown findings. Each finding must include stable id,
  file, line/range, severity, blocking boolean, confidence, evidence, and
  proposed GitHub comment text. Mark carried-forward findings as
  `source: prior_active_comment` and new findings as `source: new_finding`.
