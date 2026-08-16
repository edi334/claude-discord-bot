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
- Runs either under a dedicated low-privilege Windows account (step 3) or,
  for stronger isolation, inside a Hyper-V isolated Windows container (step
  7) that can't see the host filesystem at all beyond one mounted folder.

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
interactively over RDP — step 4 below runs its commands from *your* admin
session via `runas` instead, so it never needs its own remote session.
Keeping it out of Remote Desktop Users means even a compromised `claudebot`
password can't be used to open a graphical session on the server.

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
- Authenticate: rather than logging `claudebot` in interactively (which
  would need `runas` plus a browser inside that session), generate a
  long-lived token tied to your existing claude.ai subscription and hand it
  to the bot as an environment variable instead. On **any** machine with a
  browser — your own laptop is fine, it doesn't need to be the server or the
  `claudebot` account — run:

  ```powershell
  claude setup-token
  ```

  This prints a token valid for one year, authenticated against your
  subscription (Pro/Max/Team). Paste it into `.env` as
  `CLAUDE_CODE_OAUTH_TOKEN` in step 4 below — `claudebot` never needs to log
  in itself, and this bot's invocation doesn't use `--bare`, so it's
  compatible with that token.

  (Alternative: `ANTHROPIC_API_KEY` from https://console.anthropic.com/ also
  works, but bills separately from your subscription rather than using it.)

## 4. Configure the bot

Run this as `claudebot` so the venv and files end up owned by it, not by
you — open a fresh elevated session with:

```powershell
runas /user:claudebot powershell
```

Then, in that window:

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
- `CLAUDE_CODE_OAUTH_TOKEN` — from step 3c (`claude setup-token`)
- `CLAUDE_TOKEN_EXPIRES_ON` — today's date plus one year, e.g. if you ran
  `claude setup-token` on 2026-08-16, set `2027-08-16`. This is what powers
  the expiry warnings described below — see "Token expiry warnings".
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

## 7. Container deployment (strongest isolation — recommended over steps 3/5/6)

If you want the bot to have **zero visibility into the rest of the host
filesystem, not even read**, run it inside a Hyper-V isolated Windows
container instead of as the `claudebot` account directly. Bare metal +
Windows Server 2025 + Docker (your setup) supports this natively — no nested
virtualization needed.

With `--isolation=hyperv`, the container runs its own kernel. It cannot see
`C:\Windows`, `C:\Users`, other drives, or anything else on the host — only
whatever you explicitly mount with `-v`. This replaces steps 3 (the
low-privilege account), 5 (manual run), and 6 (Task Scheduler) entirely; you
still need steps 1, 2, and 4 (Discord app, IDs, `.env` values).

**7a. Prepare the project folder and `.env`**

You don't need the `C:\Services\claude-discord-bot` NTFS permissions from
step 3b anymore — the container boundary replaces that. You do still need
the project folder Claude is allowed to touch:

```powershell
mkdir C:\Services\claude-project
mkdir C:\Services\claude-discord-bot\logs
```

Edit `.env` (copy from `.env.example` if you haven't) with one difference
from step 4: set `CLAUDE_WORKDIR=C:\workdir` — that's the path *inside* the
container, mapped to `C:\Services\claude-project` on the host via the volume
mount in `docker-compose.yml`.

For auth, there's no browser inside the container, so run `claude setup-token`
on any machine that does have one (your laptop is fine) and put the result
in `.env` as `CLAUDE_CODE_OAUTH_TOKEN` — this authenticates against your
existing claude.ai subscription rather than a separate API key, and the
token just needs to exist as an env var inside the container, no login step
required there. (`ANTHROPIC_API_KEY` still works too, if you'd rather bill
separately via the Anthropic Console instead of your subscription.)

**7b. Build and run with Docker Compose**

`docker-compose.yml` is already in the repo, alongside the `Dockerfile`. It
builds the image, runs it with `--isolation=hyperv`, and mounts the same two
folders as before. From `C:\Services\claude-discord-bot` on the server:

```powershell
docker compose up -d --build
```

If the base image tag in the `Dockerfile`
(`python:3.12-windowsservercore-ltsc2025`) isn't published yet, swap it for
the closest available tag (e.g. `-ltsc2022`) — Hyper-V isolation doesn't
require the image build to match the host build the way process isolation
does.

I can't build/test this image myself (no Windows container runtime
available where I'm running) — build it and send me any errors and we'll
fix them together.

Useful commands:
```powershell
docker compose logs -f          # tail the bot's output
docker compose up -d --build    # rebuild and restart after editing bot.py
docker compose down             # stop and remove the container
```

- `--isolation=hyperv` is the actual isolation boundary — don't drop it.
- `--restart unless-stopped` makes Docker bring the container back after a
  reboot or crash, standing in for Task Scheduler/NSSM.
- The two `-v` mounts are the *only* host paths this container can see.
  Everything else on the server — other drives, `C:\Users`, `C:\ProgramData`,
  even most of `C:\Windows` beyond what's baked into the image — is invisible
  to it, regardless of a `tools:full` Bash command trying to reach outside
  `C:\workdir`.

Check it came up with `docker compose logs -f` — you should see the same
`Logged in as <botname>` line as the manual-run test in step 5. Test
`/claude` in Discord as before.

**To update the bot later:** edit `bot.py`/`requirements.txt`, then
`docker compose up -d --build` again.

**Optional cleanup:** if you already created the `claudebot` Windows account
for the earlier approach, you no longer need it — see "Removing the
claudebot account" below.

## Token expiry warnings

`claude setup-token` tokens are valid for one year, and it's easy to forget.
As long as `CLAUDE_TOKEN_EXPIRES_ON` is set in `.env`, the bot handles this
two ways:

- **Automatic warnings in `#claude`**, once a day, when the token has 30,
  14, 7, 3, 1, or 0 days left (configurable via `CLAUDE_TOKEN_WARN_DAYS`).
  If it's overdue, it warns every day until you fix it — it doesn't stop
  nagging on its own.
- **`/claude-status`** — run it anytime to see the workdir and a live
  countdown, without waiting for a scheduled warning.

When you get the warning: run `claude setup-token` again, update both
`CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_TOKEN_EXPIRES_ON` in `.env`, then
restart the bot (`docker compose up -d --build` for the container path, or
restart the Task Scheduler task / re-run `python bot.py` for the
account-based path).

If `CLAUDE_TOKEN_EXPIRES_ON` is left blank, none of this runs, and the bot
logs a one-time warning on startup reminding you it's not tracked.

## Removing the claudebot account

Since the bot now runs isolated in a container, `claudebot` isn't doing any
security work anymore and can be deleted. As Administrator:

```powershell
# 1. Drop its explicit permissions from the two folders (do this before
#    deleting the account, while the name still resolves)
icacls "C:\Services\claude-discord-bot" /remove claudebot
icacls "C:\Services\claude-project" /remove claudebot

# 2. If you created a Task Scheduler task for it (step 6), remove that too
Unregister-ScheduledTask -TaskName "Claudiu Remote Bot" -Confirm:$false -ErrorAction SilentlyContinue

# 3. Delete its user profile (registry hive + C:\Users\claudebot folder)
Get-CimInstance -ClassName Win32_UserProfile |
    Where-Object { $_.LocalPath -like "*\claudebot" } |
    Remove-CimInstance

# 4. Delete the account itself
Remove-LocalUser -Name "claudebot"
```

Confirm it's gone:

```powershell
Get-LocalUser -Name "claudebot"
```

This should error with "No local user found" rather than showing the
account.

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
- The real backstop for `tools:full` is whichever isolation you used: either
  `claudebot`'s limited account permissions (step 3), or, more strongly, the
  Hyper-V container boundary (step 7) — pick one, don't rely on the
  Discord-side confirmation button alone.
- Everything is logged to `logs/bot.log`, including rejected/unauthorized
  attempts and confirm/cancel/timeout decisions.
