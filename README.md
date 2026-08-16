# claude-discord-bot ("Claudiu Remote")

A minimal Discord bot that lets one authorized user run Claude Code prompts
(headless mode) against a fixed project folder on a Windows machine, via a
`/claude` slash command posted in one designated channel.

Locked down by design:
- Only the Discord user ID in `OWNER_DISCORD_ID` can trigger commands.
- Only works inside the channel ID in `CLAUDE_CHANNEL_ID` (the `#claude` channel).
- Every request runs `claude -p` in `CLAUDE_WORKDIR` with an explicit
  `--allowedTools` scope (`readonly` by default; `edit` or `full` can be
  requested per command).

## 1. Create the Discord application

1. Go to https://discord.com/developers/applications and click **New Application**.
2. Name it **Claudiu Remote**, create it.
3. Left sidebar → **Bot** → set the bot's username to **Claudiu Remote**
   too if you want it consistent → **Reset Token** → copy the token. This is
   `DISCORD_BOT_TOKEN`. Keep it secret — anyone with it can control the bot.
4. On the same Bot page, leave **Message Content Intent** off — the bot only
   uses slash commands, so it doesn't need it.
5. Left sidebar → **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Send Messages`, `Attach Files`, `Use Slash Commands`
   - Copy the generated URL, open it in a browser, and add the bot to your server.

## 2. Get your Discord user ID and the channel ID

In Discord: **User Settings → Advanced → Developer Mode** (on).

- Right-click your own name/avatar anywhere → **Copy User ID**. This is
  `OWNER_DISCORD_ID`.
- Create a text channel named `claude` in the server (if it doesn't exist
  yet), then right-click it in the channel list → **Copy Channel ID**. This
  is `CLAUDE_CHANNEL_ID`. Give the bot **View Channel** / **Send Messages**
  permission on that channel (and you can deny it access to every other
  channel — it doesn't need to see them).

## 3. Install prerequisites on the Windows machine

- Python 3.10+ (https://python.org, check "Add to PATH" during install)
- Claude Code CLI installed and working (`claude --version` from a terminal)
- Claude Code already logged in / authenticated under the Windows user account
  that will run the bot (run `claude` interactively once and complete login)

## 4. Configure the bot

```powershell
cd claude-discord-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

Fill in `.env`:
- `DISCORD_BOT_TOKEN` — from step 1
- `OWNER_DISCORD_ID` — from step 2
- `CLAUDE_CHANNEL_ID` — from step 2
- `CLAUDE_WORKDIR` — absolute path to the one project folder Claude is allowed
  to work in (create a dedicated folder if you don't want to point it at
  something sensitive)
- `CLAUDE_BIN` — usually not needed if `claude` is on PATH; set it if not

## 5. Run it once, manually

```powershell
python bot.py
```

You should see `Logged in as <botname>`. In Discord, go to the `#claude`
channel and type `/claude` — it should show up as a slash command (may take
a minute to register the first time). Try:

```
/claude prompt: list the files in this project and summarize what it does
```

Stop it with Ctrl+C once you've confirmed it works.

## 6. Run it as a Windows service (so it survives reboots/logout)

The simplest option is [NSSM](https://nssm.cc/download) (Non-Sucking Service Manager):

1. Download NSSM, extract it, and add the folder with `nssm.exe` to PATH
   (or just `cd` into it for the commands below).
2. Install the service, pointing at the venv's python and `bot.py`:

   ```powershell
   nssm install ClaudeDiscordBot "C:\path\to\claude-discord-bot\.venv\Scripts\python.exe" "C:\path\to\claude-discord-bot\bot.py"
   nssm set ClaudeDiscordBot AppDirectory "C:\path\to\claude-discord-bot"
   ```

   `AppDirectory` matters — `.env` is loaded relative to the working directory.

3. Start it:

   ```powershell
   nssm start ClaudeDiscordBot
   ```

4. Check logs at `claude-discord-bot\logs\bot.log`, or `nssm status ClaudeDiscordBot`.
5. To stop/remove later: `nssm stop ClaudeDiscordBot`, `nssm remove ClaudeDiscordBot confirm`.

(Alternative to NSSM: Task Scheduler with a trigger "At log on" or "At startup",
action = run the same python.exe with the same arguments. NSSM is more robust
because it restarts the process if it crashes.)

## Notes / limitations

- **Only readonly/edit/full tool profiles are exposed** — no arbitrary
  `--allowedTools` string from Discord. If you need another tool (e.g.
  WebSearch), add it to `TOOL_PROFILES` in `bot.py` deliberately.
- **One owner, one workdir.** If you want multiple people or multiple
  projects, add a per-user or per-role → workdir mapping in `bot.py` rather
  than accepting a path from the Discord message.
- Requests are capped at `CLAUDE_TIMEOUT_SECONDS` (default 10 minutes) and
  `CLAUDE_MAX_TURNS` (default 15) to prevent a single prompt from running away.
- Everything is logged to `logs/bot.log`, including rejected/unauthorized
  attempts.
