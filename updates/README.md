# KREW update channels

`beta.json` and `stable.json` are created by the GitHub Actions release workflow. Do not manually edit or copy manifests from untrusted sources. Users should configure `UPDATE_MANIFEST_URL=https://raw.githubusercontent.com/OWNER/REPO/main/updates/stable.json` (or beta). The repository **must be public** for anonymous update downloads.
