# GitHub App Setup

This repository owns the GitHub App manifest and operator-facing setup contract.
SAS owns the public webhook receiver and durable job queue. The existing
GitHub Actions runner path remains the production review path until the worker
and check-run publisher are implemented.

## Generate The Manifest

```sh
code-review github-app manifest \
  --name "AI Code Reviewer" \
  --url "https://example.com/code-reviewer" \
  --webhook-url "https://sas.example.com/github-code-review-app" \
  --redirect-url "https://example.com/code-reviewer/github-app/callback" \
  --output github-app-manifest.json
```

Without flags, the command prints a manifest with placeholder URLs. Override at
least `--webhook-url` before creating the app for a real environment.

The manifest subscribes only to `pull_request` events. It requests:

- `contents: read` so later workers can inspect repository content.
- `pull_requests: write` so later publishers can create review comments.
- `checks: write` so later publishers can create and update the required check.

These permissions are reserved for the app-owned worker path. The current
GitHub Actions workflow still owns review execution and the `AI Code Review`
check result.

## Create And Install The App

1. Generate the environment-specific manifest JSON.
2. POST the JSON as the `manifest` form field to GitHub's manifest flow:

   ```html
   <form action="https://github.com/organizations/ORG/settings/apps/new" method="post">
     <textarea name="manifest">{...generated manifest json...}</textarea>
     <button type="submit">Create GitHub App</button>
   </form>
   ```

   Use `https://github.com/settings/apps/new` instead for a personal-account
   app.

3. Complete GitHub's app creation page. GitHub redirects to the manifest
   `redirect_url` with a temporary `code` query parameter.
4. Exchange that code within one hour:

   ```sh
   gh api --method POST /app-manifests/CODE/conversions > github-app-credentials.json
   ```

   The response includes the app id, generated webhook secret, and private key.

5. Install the app only on repositories that should enqueue code reviews.
6. Record the app id, installation ids, webhook secret, and private key in the
   SAS secret store or deployment environment.

## SAS Interface

SAS must expose the manifest's `hook_attributes.url` as a public HTTPS endpoint
dedicated to code-review app webhooks, for example:

```text
https://sas.example.com/github-code-review-app
```

The endpoint verifies GitHub signatures using:

```text
WEBHOOK_GITHUB_CODE_REVIEW_APP_SECRET
```

The GitHub App id and private key are not needed for webhook signature
verification, but SAS should store them under the app-specific names reserved
for later worker and check-run publishing:

```text
GITHUB_CODE_REVIEW_APP_ID
GITHUB_CODE_REVIEW_APP_PRIVATE_KEY
```

If the deployment platform stores large secrets as files, use:

```text
GITHUB_CODE_REVIEW_APP_PRIVATE_KEY_FILE
```

The first SAS slice should persist verified `pull_request` webhook deliveries
and enqueue code-review jobs for `opened`, `reopened`, `synchronize`, and
`ready_for_review`. The queue payload should include at least:

- GitHub delivery id.
- Repository full name.
- Pull request number.
- Pull request URL.
- Pull request head SHA.
- Pull request action.
- Installation id.

## Check-Run Publishing Contract

The later publisher should use the app installation token to create or update a
check run named `AI Code Review` for the exact PR head SHA being reviewed. Until
that publisher exists, repositories should keep the existing GitHub Actions
workflow and branch protection configuration in place.

## Deferred Pieces

- Worker pool that leases SAS code-review jobs.
- Installation-token minting.
- Repository checkout orchestration from queued webhook jobs.
- App-owned publishing of summary comments, inline comments, and check runs.
- Migration from the Actions-required check to the app-owned required check.
