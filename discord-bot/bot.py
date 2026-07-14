import os
import sys

import discord

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

if not TOKEN:
    print("Error: DISCORD_BOT_TOKEN environment variable is not set.", file=sys.stderr)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print("Bot is online")
    print(f"Logged in as {client.user}")


def main() -> None:
    client.run(TOKEN)


if __name__ == "__main__":
    main()
