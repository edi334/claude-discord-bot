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
- `tools:full` (Bash/shell access) requires an explicit Run/Cancel button
  click before anything executes — it doesn't run automatically just because
  you typed the command. `readonly` and `edit` still run immediately.
- Runs under a dedicated low-privilege Windows account (set up in step 3
  below) instead of your main admin account, so the OS itself limits the
  blast radius if a prompt ever does something unintended.

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

## 3. Create a low-privilege Windows account for the bot

The bot (especially `tools:full`, which grants Bash) will end up running
shell commands as whatever Windows account runs `bot.py`. Running it as your
normal admin account means a bad prompt — or a successful prompt injection
from some file Claude reads — has your full permissions to work with. A
standard, non-administrator account with access to only two folders keeps
the worst case small.

**3a. Create the account**

Easiest via PowerShell, run as Administrator:

```powershell
$Password = Read-Host -AsSecureString "Password for claudebot"
New-LocalUser -Name "claudebot" -Password $Password -FullName "Claudiu Remote service account" -Description "Runs the Claude Discord bot with limited privileges"
Add-LocalGroupMember -Group "Users" -Member "claudebot"
```

Note it's added to **Users**, not **Administrators**. Confirm:

```powershell
Get-LocalGroupMember -Group "Administrators"
```

`claudebot` should not appear in that list.

(GUI alternative on Server: **Computer Management → System Tools → Local
Users and Groups → Users** → right-click → **New User…**. The consumer
"Family & other users" panel under Settings doesn't exist on Server —
`New-LocalUser`/Computer Management are the equivalents.)

**Don't add `claudebot` to Remote Desktop Users.** It doesn't need to log in
interactively over RDP — step 3c and step 4 below run its commands from
*your* admin session via `runas` instead, so it never needs its own remote
session. Keeping it out of Remote Desktop Users means even a compromised
`claudebot` password can't be used to open a graphical session on the
server.

**3b. Put the bot and the project folder somewhere claudebot can reach**

Standard Windows accounts can't see into each other's user profile folders
by default. Rather than opening up your own profile, put both folders
somewhere shared, e.g.:

```
C:\Services\claude-discord-bot      <- the bot code (this repo)
C:\Services\claude-project          <- CLAUDE_WORKDIR, the folder Claude works in
```

Then grant `claudebot` explicit **Modify** rights on both (Properties →
Security → Edit → Add → type `claudebot` → check **Modify**), or via
PowerShell:

```powershell
icacls "C:\Services\claude-discord-bot" /grant claudebot:(OI)(CI)M
icacls "C:\Services\claude-project" /grant claudebot:(OI)(CI)M
```

Everywhere else on the machine, `claudebot` only has the default standard-user
access (read/execute installed programs, no write access to your files,
system folders, or other users' profiles) — that's the actual sandbox.

**3c. Install Python and Claude Code so claudebot can use them**

- Install Python "for all users" (check that box in the installer) so it
  lands in `Program Files` and every account can run it.
- Install the Claude Code CLI (via npm — if so, install Node.js "for all
  users" too, same reasoning).
- Authenticate Claude Code as `claudebot`, without giving it a real login
  session. From your own admin PowerShell/RDP session, run:

  ```powershell
  runas /user:claudebot powershell
  ```

  Enter `claudebot`'s password when prompted — this opens a new PowerShell
  window running under `claudebot`'s account, inside your current desktop
  session (no separate RDP connection, no Remote Desktop Users membership
  needed). In that window run:

  ```powershell
  claude
  ```

  and complete login. This stores Claude's credentials under `claudebot`'s
  own profile, separate from your personal Claude session.

  **Simpler alternative:** if you'd rather skip the interactive/browser login
  entirely, Claude Code also accepts an API key via the `ANTHROPIC_API_KEY`
  environment variable — set that for `claudebot` (e.g. in the `.env` file in
  step 4, or as a user environment variable on that account) instead of
  running `claude` to log in. Cleaner for a service account, and avoids any
  browser-launching-under-a-different-user complications on a server.

## 4. Configure the bot

Keep using that same `runas /user:claudebot powershell` window for
everything below, so files end up owned by `claudebot`, not by you:

```powershell
cd C:\Services\claude-discord-bot
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
- `CLAUDE_WORKDIR` — `C:\Services\claude-project` (or wherever you put it in step 3b)
- `CLAUDE_BIN` — usually not needed if `claude` is on PATH; set it if not
- `CLAUDE_CONFIRM_TIMEOUT_SECONDS` — optional, how long the Run/Cancel button
  waits for `tools:full` requests before auto-cancelling (default 60)

## 5. Run it once, manually

Still in the `runas` window (running as `claudebot`):

```powershell
python bot.py
```

You should see `Logged in as <botname>`. In Discord, go to the `#claude`
channel and type `/claude` — it should show up as a slash command (may take
a minute to register the first time). Try:

```
/claude prompt: list the files in this project and summarize what it does
```

Then try a `tools:full` request and confirm the Run/Cancel buttons appear
and block execution until you click **Run it**.

Stop it with Ctrl+C once you've confirmed it works.

## 6. Run it automatically as claudebot (Task Scheduler)

NSSM's normal install path runs a service as SYSTEM or whatever account is
logged in, and switching a service to another account needs the "Log on as
a service" right, which requires `secpol.msc` — not available on Windows
Home. Task Scheduler avoids that: when you give it stored credentials for a
task, Windows grants the needed right automatically, and it works on every
Windows edition.

1. Open **Task Scheduler** (Start menu → **Windows Administrative Tools** →
   Task Scheduler, or `taskschd.msc`) → **Create Task…** (not "Create Basic
   Task", you need the extra options).
2. **General** tab:
   - Name: `Claudiu Remote Bot`
   - **Change User or Group…** → select `claudebot`
   - Select **Run whether user is logged on or not**
   - Leave **Run with highest privileges** unchecked (that's the point)
3. **Triggers** tab → **New…** → Begin the task: **At startup**.
4. **Actions** tab → **New…**:
   - Program/script: `C:\Services\claude-discord-bot\.venv\Scripts\pythonw.exe`
     (`pythonw` instead of `python` so no console window appears)
   - Add arguments: `bot.py`
   - Start in: `C:\Services\claude-discord-bot`
5. **Settings** tab: check **If the task fails, restart every** → `1 minute`,
   a few attempts, so the bot recovers if it ever crashes.
6. Click **OK**, enter `claudebot`'s password when prompted.
7. Right-click the task → **Run** to test it immediately without rebooting.
   Check `logs\bot.log` in the bot folder, or Task Scheduler's **History**
   tab, to confirm it started.

To stop/disable later: right-click the task → **Disable** or **End**.

## Notes / limitations

- **Only readonly/edit/full tool profiles are exposed** — no arbitrary
  `--allowedTools` string from Discord. If you need another tool (e.g.
  WebSearch), add it to `TOOL_PROFILES` in `bot.py` deliberately.
- **One owner, one workdir.** If you want multiple people or multiple
  projects, add a per-user or per-role → workdir mapping in `bot.py` rather
  than accepting a path from the Discord message.
- Requests are capped at `CLAUDE_TIMEOUT_SECONDS` (default 10 minutes) and
  `CLAUDE_MAX_TURNS` (default 15) to prevent a single prompt from running away.
- `tools:full` additionally requires a Run/Cancel button click, owner-only,
  before the command executes.
- `claudebot`'s account permissions are the real backstop for `tools:full` —
  keep it out of the Administrators group and don't grant it access beyond
  the two folders in step 3b.
- Everything is logged to `logs/bot.log`, including rejected/unauthorized
  attempts and confirm/cancel/timeout decisions.
