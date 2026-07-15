---
name: Publishing non-artifact background processes
description: How to make the Discord bot (a plain workflow, not an artifact) run in the published deployment of this pnpm-workspace project.
---

# Publishing non-artifact background processes (e.g. the Discord bot)

The Publish pane only counts deployable-kind artifacts (web/mobile). Artifacts of kind
`api` and `design` do NOT open the publish gate, even with a `[services.production]`
section. A plain workflow process (like the Python Discord bot) is invisible to publishing.

**How this project was made publishable (July 2026):**
1. A real web artifact at previewPath `/` (AlphaOptionsAI landing page) — this alone flips
   "Project artifacts are not deployable" to deployable.
2. `.replit` `deploymentTarget` set to `vm` (Reserved VM) — required for the bot's
   persistent Discord gateway connection; autoscale would suspend it between requests.
   `.replit` cannot be edited directly: write full TOML to a temp file and call
   `verifyAndReplaceDotReplit({ tempFilePath })`.
3. The bot rides along with the api-server artifact's production service:
   `[services.production.run]` runs `bash scripts/production-run.sh`, which starts the
   node API server (serves the /api/healthz health check) AND `python discord-bot/bot.py`,
   and exits if either dies so the VM restarts the container.

**Why:** there is no artifact type for Python background workers, so piggybacking on an
existing production service is the supported-shape workaround.

**How to apply:** if the bot's production entrypoint changes, edit
`scripts/production-run.sh` — not the artifact.toml run args. Never point the deployment
at the bot alone: the health check depends on the node server listening on PORT 8080.
