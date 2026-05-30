Review this PR for design, layering, abstraction boundaries, and reuse.

Original review payload:
$ARGUMENTS

Prepared worktree:
$prepare_worktree.output

Review brief:
$summarize_intent.output

Requirements:
- Review exactly the supplied head SHA, never a moving branch reference.
- Do not call `gh`, the GitHub API, or network tools. GitHub context is already
  summarized in the review brief.
- Explore the surrounding codebase when needed, not only the diff.
- Check whether similar behavior, components, helpers, services, or provider
  abstractions already exist and should have been reused.
- Identify duplicated behavior introduced by the PR.
- Check whether files/modules are taking on the right responsibilities or
  becoming dumping grounds.
- Check whether concerns should be split into components, utilities,
  classes, services, adapters, or provider-specific modules.
- Check whether provider/vendor details leak across layers instead of being
  hidden behind local abstractions.
- Avoid subjective style feedback. Tie every finding to real maintainability,
  correctness, reuse, or future-change risk.
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
