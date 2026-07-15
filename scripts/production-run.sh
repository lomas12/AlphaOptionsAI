#!/usr/bin/env bash
# Production entrypoint for the published (Reserved VM) deployment.
#
# Runs the API server (serves /api plus the deployment health check) and the
# AlphaOptionsAI Discord bot side by side. The bot is a plain Python process,
# not a workspace artifact, so it rides along with the API server's
# production service.
#
# Supervision model: if either process exits, tear down the other and exit
# non-zero so the VM restarts the whole container cleanly rather than
# limping along half-up. SIGTERM/SIGINT from the platform are forwarded to
# both children so shutdowns are clean.

node --enable-source-maps artifacts/api-server/dist/index.mjs &
NODE_PID=$!

python discord-bot/bot.py &
BOT_PID=$!

cleanup() {
  trap - TERM INT
  kill "$NODE_PID" "$BOT_PID" 2>/dev/null
  wait 2>/dev/null
}

trap 'cleanup; exit 143' TERM INT

# Block until EITHER child exits (bot self-restarts via os.execv keep the
# same PID, so they do NOT trip this).
wait -n

echo "A production process exited; restarting container..." >&2
cleanup
exit 1
