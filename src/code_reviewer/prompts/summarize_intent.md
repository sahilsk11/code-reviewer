Create the shared intent and context brief for this pull request.

Original review payload:
$ARGUMENTS

Prepared worktree:
$prepare_worktree.output

Collected GitHub context:
$collect_github_context.output

Canonical implementation transcript:
$find_implementation_transcript.output

Use the collected GitHub context and prepared worktree. Do not call `gh`, the
GitHub API, or network tools from this node.

Required context to inspect from the supplied context:
- PR title, body, commits, base/head SHAs, changed files, and diff overview.
- Linked ticket if one is obvious from the branch name, PR body, commits,
  issue keys, or PR references.
- Prior PR issue comments, review comments, and review threads.
- Reviewer controls: pause, resume, full, incremental, ignore, and resolve.
- The selected cleaned Kanna transcript when `find_implementation_transcript`
  selected one.
- User-facing or system flows affected by the change.

Produce a concise Markdown brief with:
- What the PR is trying to achieve.
- Specific user requests, constraints, and non-goals.
- Any likely user intent drift: places where the implementation might solve
  an adjacent problem instead of the requested one.
- Prior review state that should affect this run, grouped into:
  - Active unresolved blocking comments: prior AI blocking comments on
    current, non-outdated diff lines with no human reply or resolve/ignore
    control. These still count as blockers unless the current diff clearly
    fixed them.
  - Active unresolved non-blocking comments: prior AI comments on current,
    non-outdated diff lines with no human reply or resolve/ignore control.
    Do not repost these as duplicates.
  - Responded-to comments: threads with human replies such as disagreement,
    explanation, "fixed", or other discussion. Treat these as context for
    the reviewers, not automatic blockers or duplicate suppressors.
  - Outdated comments: GitHub review threads/comments marked outdated or
    anchored to an older diff. Use these only as history. Do not suppress a
    fresh finding on current broken code because an outdated comment exists.
  - Explicit controls: ignore, resolve, pause, resume, full, incremental,
    and any comment-specific controls.
- Quotes from PR text or transcript messages when they materially support intent.
- Linked-ticket context that materially changes how the diff should be read.
- A short list of affected flows that reviewers should trace beyond the diff.
- Any missing context that reviewers should not guess around.

Do not perform the code review in this node.
