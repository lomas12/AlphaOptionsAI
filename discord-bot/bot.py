import os
import sys

import discord
from discord import app_commands

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

if not TOKEN:
    print("Error: DISCORD_BOT_TOKEN environment variable is not set.", file=sys.stderr)
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True


class AlphaOptionsAIClient(discord.Client):
    def __init__(self, *, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)


client = AlphaOptionsAIClient(intents=intents)


@client.tree.command(name="ping", description="Check if AlphaOptionsAI is online")
async def ping(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("🏓 Pong! AlphaOptionsAI is online.")


@client.event
async def on_ready():
    await client.tree.sync()
    print("Bot is online")
    print(f"Logged in as {client.user}")


def main() -> None:
    client.run(TOKEN)


if __name__ == "__main__":
    main()
