---
name: find-eval-cases
description: Mine recently merged GitHub pull requests for validated reviewer findings that can become curated Braintrust eval cases.
compatibility: codex
---

# Find Eval Cases

Use this skill when the user asks to find more eval cases, mine recent PRs for review examples, or expand the reviewer correctness/regressions eval with real pull request fixtures.

This is a repository-level workflow. Do not use `skillify` or install a global/server-level skill for this.

## Goal

Find merged PRs that can become stable eval fixtures for `evals/reviewer_correctness_regressions.py`.

A good case is not just a PR. A good case is:

- a stable repo + base SHA + head SHA pair,
- a concrete reviewer-worthy issue in that diff,
- evidence that the issue was valid, usually a `[REVIEW_GRADE:VALID]` or `[REVIEW_GRADE:PARTIAL]` comment,
- a concise `must_notice_terms` set that can score whether the reviewer output found the issue.

## Search Scope

Start with this repository unless the user names other repositories. Then expand to recently active repos owned by the user.

Useful starting commands:

```sh
gh pr list --repo sahilsk11/code-reviewer --state merged --limit 30 \
  --json number,title,url,mergedAt,baseRefOid,headRefOid,comments,files,commits
```

For another repo:

```sh
gh pr list --repo OWNER/REPO --state merged --limit 30 \
  --json number,title,url,mergedAt,baseRefOid,headRefOid,comments,files,commits
```

If broader repo discovery is needed:

```sh
gh repo list sahilsk11 --limit 50 --json nameWithOwner,pushedAt,isPrivate
```

Prefer recently pushed repositories and recently merged PRs.

## Candidate Signals

Strong positive signals:

- PR comments or review comments contain `[REVIEW_GRADE:VALID]`.
- PR comments or review comments contain `[REVIEW_GRADE:PARTIAL]` and describe a real narrowed bug.
- A review comment identifies a concrete file/function/behavior.
- A follow-up commit after the review comment plausibly fixes the issue.
- The PR is merged and has immutable base/head SHAs.
- The diff is small enough for a reviewer eval to be focused.

Negative signals:

- Docs-only, dependency-only, formatting-only, or pure cleanup PRs.
- Huge refactors where one expected issue is hard to isolate.
- Findings that depend on private context not visible in the diff.
- Comments graded invalid, false positive, speculative, or style-only.
- Bugs that were pre-existing and not introduced or exposed by the PR diff, unless the eval goal explicitly wants “missed pre-existing bug visible in changed code.”

## Inspect A Candidate

For each promising PR, inspect comments and changed files:

```sh
gh pr view PR_NUMBER --repo OWNER/REPO \
  --json number,title,url,body,comments,reviews,files,commits,baseRefOid,headRefOid
```

If inline review threads matter, use GitHub GraphQL through `gh api graphql` to inspect review comments and positions. Otherwise top-level comments are enough for the first pass.

Look for a chain like:

1. Reviewer comment describes a bug.
2. Grade comment marks it valid or partial.
3. Follow-up commit fixes or mitigates it.

## Pick Cases

Prefer adding one or two high-quality cases over many weak cases.

For each selected case, record:

- `name`: short stable slug, usually `<repo>-<issue>`.
- `repo`: clone URL, usually `https://github.com/OWNER/REPO.git`.
- `base_sha`: the PR base SHA before the relevant reviewed change.
- `head_sha`: the pre-fix reviewed commit when the bug was present.
- `source_pr`: PR URL.
- `title` and `body`: PR title/body summary.
- `validated_comments`: grade, URL, and concise finding text.
- `must_notice`: human-readable issue statements.
- `must_notice_terms`: term groups for `known_issue_present`.
- `avoid`: common false-positive or overfitting traps.

Important: use the commit where the bug exists as `head_sha`, not the final merged commit if later commits fixed the finding.

## Add The Case

Edit `evals/reviewer_correctness_regressions.py` and append the case to `CASES`.

Keep `must_notice_terms` specific enough to catch the issue, but not so specific that only exact wording passes. Use grouped alternatives for synonyms:

```python
"must_notice_terms": [
    ["count_blocking"],
    ["blocking_count"],
    ["blocking: true", "blocking true", "per-comment"],
    ["mask", "override", "undercount", "ignore", "non-blocking"],
],
```

Add or update tests in `tests/test_reviewer_correctness_regressions_eval.py` so the source PR, commit pair, and key scoring terms are pinned.

## Verify

Run focused checks first:

```sh
.venv/bin/python -m ruff check evals/reviewer_correctness_regressions.py tests/test_reviewer_correctness_regressions_eval.py
.venv/bin/python -m pyright
.venv/bin/python -m pytest tests/test_reviewer_correctness_regressions_eval.py
```

Then run the full suite:

```sh
.venv/bin/python -m pytest
```

If requested, use the `run-evals` skill afterward to run Braintrust evals and post results to the PR.

## Report

When handing back findings or a PR, include:

- candidate PRs inspected,
- which case(s) were added,
- why each case is a good eval fixture,
- verification run,
- remaining candidates worth mining next.

If no suitable case is found, report the best candidates rejected and why. Do not add weak cases just to increase count.
