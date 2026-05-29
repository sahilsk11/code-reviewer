Review this PR for simplicity, directness, and better alternatives.

Original review payload:
$ARGUMENTS

Prepared worktree:
$prepare_worktree.output

Review brief:
$summarize_intent.output

Requirements:
- Review exactly the supplied head SHA, never a moving branch reference.
- Decide whether the implementation is the simplest good solution for the
  actual user intent.
- Look for roundabout implementations, unnecessary machinery, premature
  abstractions, avoidable state, overbroad refactors, or complex approaches
  where a local pattern would have been cleaner.
- Identify better alternatives only when they are concrete and materially
  better. It is acceptable to say the current approach is reasonable.
- Separate actionable review comments from summary-only tradeoffs.
- Do not raise style feedback, preference-only feedback, or speculative
  architecture advice.
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
