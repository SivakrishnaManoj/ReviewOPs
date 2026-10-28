# Working together

1. Clone the private repository using your own GitHub access.
2. Pull `main`, then create a focused feature branch.
3. Run the local app and checks described in the README.
4. Push the branch and open a PR. Include what changed and how you tested it.
5. Wait for the checks and one teammate's review before merging.

S. adds both teammates as collaborators in the repository settings; do not share tokens.
On `main`, enable a branch rule/ruleset requiring pull requests and the `checks`,
`infrastructure`, and `container` status checks, with one approving review where your
GitHub plan supports those controls for private repositories. Keep force pushes disabled.
The scaffold does not configure repository settings or invite collaborators automatically.

Append numbered SQL migrations; never edit a migration already applied to a shared
database. Migration checksums deliberately reject changed history. Use backwards-compatible
schema changes so a previous application image can still run during rollback.

Keep prompts, credentials, request bodies, raw reviews, and local files out of logs and
Git. Add a tiny synthetic fixture when a test needs data. AI unit tests should mock model
calls; run paid evaluation separately on an explicitly selected dataset.

The delivery workflow only assumes the AWS role from `main`. PRs run tests without AWS
credentials. Infrastructure is reviewed and applied by S.; ordinary application PRs do
not gain Terraform or account-administration permissions.
