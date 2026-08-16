"""
Discord -> Claude Code bridge ("Claudiu Remote").

Lets one authorized Discord user run Claude Code prompts (headless mode)
against a fixed local project folder, from a /claude slash command posted
in a single designated Discord channel.
"""

import asyncio
import contextlib
import datetime
import json
import logging
import os
import shlex
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OWNER_DISCORD_ID = int(os.environ["OWNER_DISCORD_ID"])
CLAUDE_CHANNEL_ID = int(os.environ["CLAUDE_CHANNEL_ID"])
CLAUDE_WORKDIR = Path(os.environ["CLAUDE_WORKDIR"]).resolve()
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "600"))
MAX_TURNS = os.environ.get("CLAUDE_MAX_TURNS", "15")
CONFIRM_TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_CONFIRM_TIMEOUT_SECONDS", "60"))

_expires_raw = os.environ.get("CLAUDE_TOKEN_EXPIRES_ON", "").strip()
TOKEN_EXPIRES_ON: datetime.date | None = (
    datetime.date.fromisoformat(_expires_raw) if _expires_raw else None
)
TOKEN_WARN_DAYS = {
    int(x) for x in os.environ.get("CLAUDE_TOKEN_WARN_DAYS", "30,14,7,3,1,0").split(",") if x.strip()
}

TOOL_PROFILES = {
    "readonly": "Read,Grep,Glob",
    "edit": "Read,Grep,Glob,Edit,Write",
    "full": "Read,Grep,Glob,Edit,Write,Bash",
}

# Profiles that require an explicit button-click confirmation before running.
CONFIRM_REQUIRED = {"full"}

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

if TOKEN_EXPIRES_ON is None:
    log.warning(
        "CLAUDE_TOKEN_EXPIRES_ON is not set — the bot can't warn you before "
        "the Claude Code auth token expires. Set it in .env (see .env.example)."
    )

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


class ConfirmView(discord.ui.View):
    """Owner-only Run/Cancel buttons, used to gate risky tool profiles."""

    def __init__(self, owner_id: int, timeout: float = CONFIRM_TIMEOUT_SECONDS):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.value: bool | None = None  # None = timed out with no click
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This confirmation isn't yours to answer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Run it", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.edit_message(content="✅ Confirmed — running…", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled — nothing was run.", view=None)

    async def on_timeout(self):
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(content="⌛ Confirmation timed out — nothing was run.", view=None)


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

    if tool_profile in CONFIRM_REQUIRED:
        view = ConfirmView(OWNER_DISCORD_ID)
        await interaction.response.send_message(
            f"⚠️ **{tool_profile}** access requested (includes Bash/shell execution):\n"
            f"```\n{prompt[:1500]}\n```\nConfirm within {CONFIRM_TIMEOUT_SECONDS}s.",
            view=view,
        )
        view.message = await interaction.original_response()
        await view.wait()
        if not view.value:
            log.info(
                "User %s did not confirm [%s] request (timed out=%s): %s",
                interaction.user, tool_profile, view.value is None, prompt,
            )
            return
        log.info("User %s confirmed [%s] request: %s", interaction.user, tool_profile, prompt)
    else:
        await interaction.response.defer(thinking=True)
        log.info("User %s requested [%s]: %s", interaction.user, tool_profile, prompt)

    start = time.monotonic()
    ok, result = await run_claude(prompt, tool_profile)
    elapsed = time.monotonic() - start

    header = (
        f"<@{OWNER_DISCORD_ID}> {'✅' if ok else '❌'} `{tool_profile}` · "
        f"{elapsed:.1f}s\n"
    )
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


def _token_status_line() -> str:
    if TOKEN_EXPIRES_ON is None:
        return "⚪ Claude token expiry not tracked (set `CLAUDE_TOKEN_EXPIRES_ON` in `.env`)."
    days_left = (TOKEN_EXPIRES_ON - datetime.date.today()).days
    if days_left < 0:
        return f"🔴 Claude token **expired {abs(days_left)} day(s) ago** ({TOKEN_EXPIRES_ON.isoformat()})."
    if days_left == 0:
        return f"🟠 Claude token **expires today** ({TOKEN_EXPIRES_ON.isoformat()})."
    return f"🟢 Claude token expires in **{days_left} day(s)** ({TOKEN_EXPIRES_ON.isoformat()})."


@tree.command(name="claude-status", description="Show the bot's config and Claude auth token expiry")
async def claude_status_command(interaction: discord.Interaction):
    if interaction.user.id != OWNER_DISCORD_ID:
        await interaction.response.send_message(
            "You're not authorized to run this command.", ephemeral=True
        )
        return

    if interaction.channel_id != CLAUDE_CHANNEL_ID:
        await interaction.response.send_message(
            "This command only works in the #claude channel.", ephemeral=True
        )
        return

    lines = [f"Workdir: `{CLAUDE_WORKDIR}`", _token_status_line()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tasks.loop(hours=24)
async def check_token_expiry():
    if TOKEN_EXPIRES_ON is None:
        return

    days_left = (TOKEN_EXPIRES_ON - datetime.date.today()).days
    if days_left not in TOKEN_WARN_DAYS and days_left >= 0:
        return

    channel = client.get_channel(CLAUDE_CHANNEL_ID)
    if channel is None:
        log.warning("Can't find channel %s to send token expiry warning", CLAUDE_CHANNEL_ID)
        return

    mention = f"<@{OWNER_DISCORD_ID}>"
    if days_left < 0:
        msg = (
            f"🔴 {mention} The Claude Code auth token **expired {abs(days_left)} day(s) ago** "
            f"({TOKEN_EXPIRES_ON.isoformat()}). Run `claude setup-token`, update "
            f"`CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_TOKEN_EXPIRES_ON` in `.env`, then restart the bot."
        )
    elif days_left == 0:
        msg = (
            f"🟠 {mention} The Claude Code auth token **expires today** "
            f"({TOKEN_EXPIRES_ON.isoformat()}). Run `claude setup-token` to renew it."
        )
    else:
        msg = (
            f"🟡 {mention} The Claude Code auth token expires in **{days_left} day(s)** "
            f"({TOKEN_EXPIRES_ON.isoformat()}). Run `claude setup-token` to renew it, then "
            f"update `CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_TOKEN_EXPIRES_ON` in `.env` and restart."
        )

    await channel.send(msg)
    log.info("Sent token expiry warning: %s day(s) left", days_left)


@client.event
async def on_ready():
    await tree.sync()
    if TOKEN_EXPIRES_ON is not None and not check_token_expiry.is_running():
        check_token_expiry.start()
    log.info(
        "Logged in as %s. Workdir: %s. Restricted to channel ID %s. %s",
        client.user, CLAUDE_WORKDIR, CLAUDE_CHANNEL_ID, _token_status_line(),
    )


if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN, log_handler=None)
