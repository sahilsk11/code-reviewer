Identify the canonical implementation transcript for this pull request, if one exists.

Original review payload:
$ARGUMENTS

Use this helper command to produce normalized candidate transcripts and a
readable candidate report:

```sh
"${CODE_REVIEW_PYTHON:-python3}" -m code_reviewer.commands.discover_transcripts \
  --payload-json '$ARGUMENTS' \
  --kanna-root "$HOME/.kanna" \
  --cleaner loki \
  --optional
```

Then inspect the candidate report and read only the normalized transcript
files needed to decide which session actually contains the implementation
work for this PR. Prefer transcripts that include the PR URL, PR shorthand,
branch/head SHA, implementation discussion, commits, review fixes, or final
PR handoff. Do not select a transcript merely because it mentions the repo
or uses this PR as sample/demo data.

Output concise Markdown:
- Selected transcript: `<normalized transcript path>` or `none`
- Source transcript: `<source transcript path>` or `none`
- Confidence: high, medium, low, or none
- Reason: 1-3 bullets explaining why this is the implementation transcript
- Useful quotes: at most 3 short user quotes, only if they clarify intent
