---
name: GitHub push credentials
description: Why git pushes fail with NO_CREDENTIALS even when the GitHub connector integration is attached
---

# GitHub pushes need the account-level GitHub link, not the connector

**The rule:** The GitHub *connector* integration (OAuth app, `connectors.proxy("github", ...)`) is proxy-scoped: the sandbox never receives the raw token (`listConnections('github')` returns `[]` by design for it, and the SDK only exposes `proxy`/`getProxyUrl`/`getProxyHeaders`). It authenticates REST API calls only. Actual `git push` via the `gitPush` callback requires the user's **account-level GitHub source-control link** (connected from the workspace Git pane). Without it, `gitPush` fails with `NO_CREDENTIALS: "No github-source-control credentials found"` — attaching the connector does not fix this.

**Why:** Confirmed 2026-07-15: connector attached and verified working (repo metadata + `pushPermission: true` via proxy), yet `gitPush` still returned NO_CREDENTIALS and no raw token was obtainable through any documented path.

**How to apply:** If a push fails with NO_CREDENTIALS, don't propose/attach the GitHub connector expecting it to fix pushes, and don't hunt for the token in the sandbox. Ask the user to connect GitHub from the Git pane, then retry `gitPush`. A REST-based push via the Git Data API is possible but creates a commit hash that diverges from local history — avoid it.
