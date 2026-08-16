"""
Discord -> Claude Code bridge ("Claudiu Remote").

Lets one authorized Discord user run Claude Code prompts (headless mode)
against a fixed local project folder, from a /claude slash command posted
in a single designated Discord channel.
"""

import asyncio
import json
import logging
import os
import shlex
import time
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OWNER_DISCORD_ID = int(os.environ["OWNER_DISCORD_ID"])
CLAUDE_CHANNEL_ID = int(os.environ["CLAUDE_CHANNEL_ID"])
CLAUDE_WORKDIR = Path(os.environ["CLAUDE_WORKDIR"]).resolve()
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "600"))
MAX_TURNS = os.environ.get("CLAUDE_MAX_TURNS", "15")

TOOL_PROFILES = {
    "readonly": "Read,Grep,Glob",
    "edit": "Read,Grep,Glob,Edit,Write",
    "full": "Read,Grep,Glob,Edit,Write,Bash",
}

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("claude-discord-bot")

if not CLAUDE_WORKDIR.is_dir():
    raise SystemExit(f"CLAUDE_WORKDIR does not exist: {CLAUDE_WORKDIR}")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


async def run_claude(prompt: str, tool_profile: str) -> tuple[bool, str]:
    allowed_tools = TOOL_PROFILES[tool_profile]
    cmd = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--allowedTools",
        allowed_tools,
        "--max-turns",
        str(MAX_TURNS),
    ]
    log.info("Running: %s (cwd=%s)", shlex.join(cmd), CLAUDE_WORKDIR)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(CLAUDE_WORKDIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=CLAUDE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"Timed out after {CLAUDE_TIMEOUT_SECONDS}s and was killed."

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        return False, f"claude exited {proc.returncode}\n{stderr_text or stdout_text}"

    try:
        payload = json.loads(stdout_text)
    except json.JSONDecodeError:
        return True, stdout_text or "(no output)"

    if payload.get("is_error"):
        return False, payload.get("result", stdout_text)

    return True, payload.get("result", stdout_text)


@tree.command(name="claude", description="Run a Claude Code prompt against the configured project folder")
@app_commands.describe(
    prompt="What you want Claude to do",
    tools="How much tool access to grant for this request",
)
@app_commands.choices(
    tools=[
        app_commands.Choice(name="readonly (Read/Grep/Glob)", value="readonly"),
        app_commands.Choice(name="edit (+ Edit/Write)", value="edit"),
        app_commands.Choice(name="full (+ Bash)", value="full"),
    ]
)
async def claude_command(
    interaction: discord.Interaction,
    prompt: str,
    tools: app_commands.Choice[str] = None,
):
    if interaction.user.id != OWNER_DISCORD_ID:
        await interaction.response.send_message(
            "You're not authorized to run this command.", ephemeral=True
        )
        log.warning("Rejected command from unauthorized user %s (%s)", interaction.user, interaction.user.id)
        return

    if interaction.channel_id != CLAUDE_CHANNEL_ID:
        await interaction.response.send_message(
            "This command only works in the #claude channel.", ephemeral=True
        )
        log.warning(
            "Rejected command in wrong channel %s (%s) from %s",
            getattr(interaction.channel, "name", "?"), interaction.channel_id, interaction.user,
        )
        return

    tool_profile = tools.value if tools else "readonly"
    await interaction.response.defer(thinking=True)

    log.info("User %s requested [%s]: %s", interaction.user, tool_profile, prompt)
    start = time.monotonic()
    ok, result = await run_claude(prompt, tool_profile)
    elapsed = time.monotonic() - start

    header = f"{'✅' if ok else '❌'} `{tool_profile}` · {elapsed:.1f}s\n"
    body = result if result else "(empty result)"

    if len(header) + len(body) <= 1900:
        await interaction.followup.send(header + "```\n" + body[:1900] + "\n```")
    else:
        out_path = LOG_DIR / f"result-{int(time.time())}.txt"
        out_path.write_text(body, encoding="utf-8")
        await interaction.followup.send(
            header + "Result was too long, attached as a file.",
            file=discord.File(out_path),
        )


@client.event
async def on_ready():
    await tree.sync()
    log.info(
        "Logged in as %s. Workdir: %s. Restricted to channel ID %s.",
        client.user, CLAUDE_WORKDIR, CLAUDE_CHANNEL_ID,
    )


if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN, log_handler=None)
