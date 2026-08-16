# claude-discord-bot ("Claudiu Remote")

A minimal Discord bot that lets one authorized user run Claude Code prompts
(headless mode) against a fixed project folder, via a `/claude` slash
command posted in one designated channel. Deployable on a Windows account
or on a Linux MicroK8s cluster.

Locked down by design:
- Only the Discord user ID in `OWNER_DISCORD_ID` can trigger commands.
- Only works inside the channel ID in `CLAUDE_CHANNEL_ID` (the `#claude` channel).
- Every request runs `claude -p` in `CLAUDE_WORKDIR` with an explicit
  `--allowedTools` scope (`readonly` by default; `edit` or `full` can be
  requested per command).
- `tools:full` (Bash/shell access) requires an explicit Run/Cancel button
  click before anything executes — it doesn't run automatically just because
  you typed the command. `readonly` and `edit` still run immediately.
- Runs under a dedicated low-privilege Windows account (step 3), or on a
  Linux MicroK8s cluster (step 7) — pick whichever matches your
  infrastructure.

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

## 7. MicroK8s deployment (Linux, alternative to steps 3-6)

If you already run a MicroK8s (or any Kubernetes) cluster on a Linux host,
this is simpler than the Windows account path above: smaller images
(`python:3.12-slim` vs. multi-GB Windows base images), Bash works natively
instead of needing Git Bash, and there's no Windows image-tag/registry
flakiness to fight. Uses `Dockerfile` and the manifests in `deploy/`.

Still need steps 1 and 2 (Discord app, IDs). Skip 3 through 6 entirely.

**7a. Create the two host directories**, on whichever node will run the pod
(for a single-node MicroK8s VM, that's just the VM itself):

```bash
sudo mkdir -p /opt/claude-discord-bot/workdir /opt/claude-discord-bot/logs
sudo chown -R 10001:10001 /opt/claude-discord-bot
```

uid `10001` is the non-root `claudebot` user baked into the image by the
`Dockerfile` — keep them matching if you change one. `workdir` is
`CLAUDE_WORKDIR`, the only folder Claude can touch; `logs` is where
`bot.log` and long results land.

**7b. Configure `deploy/secret.yaml`**

Unlike the Windows paths, this one doesn't use `.env` at all — the bot's
config and secrets come from a Kubernetes `Secret` object instead.
`deploy/secret.yaml` is already in the repo (and, like the rest of
`deploy/`, gitignored) with the fields laid out and commented:

```bash
$EDITOR deploy/secret.yaml
```

Replace the `REPLACE_ME` placeholders: `DISCORD_BOT_TOKEN`,
`OWNER_DISCORD_ID`, `CLAUDE_CHANNEL_ID` (steps 1–2), and
`CLAUDE_CODE_OAUTH_TOKEN` / `CLAUDE_TOKEN_EXPIRES_ON` (from
`claude setup-token`, run on any machine with a browser). Leave
`CLAUDE_WORKDIR: "/workdir"` as-is — that's the in-container mount path,
mapped to `/opt/claude-discord-bot/workdir` on the node via the `hostPath`
volume in `deploy/deployment.yaml`.

**7c. Build and push the image**

```bash
./build.sh
```

Same pattern as your other deployed apps — builds and pushes to
`188.34.177.197:32000/claude-discord-bot:latest`, the same registry
`deploy/deployment.yaml` pulls from. `build.sh` is gitignored (like the rest
of `deploy/`), so it stays local rather than getting committed.

(If that registry isn't reachable from wherever you're building — e.g.
you're on a machine without network access to it — the no-registry
alternative is to build directly on the cluster node and
`docker save claude-discord-bot:latest | microk8s ctr image import -`, then
switch `deploy/deployment.yaml`'s `image:` to `claude-discord-bot:latest` with
`imagePullPolicy: Never`.)

**7d. Deploy**

```bash
microk8s kubectl apply -f deploy/namespace.yaml
microk8s kubectl apply -f deploy/secret.yaml
microk8s kubectl apply -f deploy/deployment.yaml
```

(Drop the `microk8s` prefix if you've already aliased `kubectl` to it.)

**7e. Verify**

```bash
microk8s kubectl -n claude-discord-bot logs -f deploy/claude-discord-bot
```

Look for `Logged in as Claudiu Remote`, then test `/claude` and
`/claude-status` in the `#claude` channel as before.

**Updating the bot later:**

```bash
./build.sh
microk8s kubectl -n claude-discord-bot rollout restart deploy/claude-discord-bot
```

**Rotating the token / editing config** (e.g. after a `claude setup-token`
renewal): edit `deploy/secret.yaml`, re-apply it, then restart the pod so it
picks up the change (updating a Secret doesn't automatically restart pods
already using it):

```bash
$EDITOR deploy/secret.yaml
microk8s kubectl apply -f deploy/secret.yaml
microk8s kubectl -n claude-discord-bot rollout restart deploy/claude-discord-bot
```

**Isolation note:** `deploy/deployment.yaml` runs the container as a non-root
user with all Linux capabilities dropped, which is solid baseline hardening,
but it's still standard containerd/runc isolation — a shared kernel with the
host, not an airtight per-pod VM boundary. That's a reasonable tradeoff on a
MicroK8s box you already trust with other workloads, but it's worth knowing:
a "can't see the host at all" guarantee here would need a hardened runtime
class (gVisor or Kata) added to MicroK8s, which these manifests don't set up.

**Keep `replicas: 1`.** A second pod would open a second Discord gateway
connection using the same bot token and fight the first one — don't scale
this deployment.

## Token expiry warnings

`claude setup-token` tokens are valid for one year, and it's easy to forget.
As long as `CLAUDE_TOKEN_EXPIRES_ON` is set (`.env` for the account-based
path, `deploy/secret.yaml` for MicroK8s), the bot handles this two ways:

- **Automatic warnings in `#claude`**, once a day, when the token has 30,
  14, 7, 3, 1, or 0 days left (configurable via `CLAUDE_TOKEN_WARN_DAYS`).
  If it's overdue, it warns every day until you fix it — it doesn't stop
  nagging on its own.
- **`/claude-status`** — run it anytime to see the workdir and a live
  countdown, without waiting for a scheduled warning.

When you get the warning: run `claude setup-token` again, then update both
`CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_TOKEN_EXPIRES_ON` and restart —
for the account-based path, edit `.env` and restart the Task Scheduler task
/ re-run `python bot.py`; for MicroK8s, see "Rotating the token" under
step 7.

If `CLAUDE_TOKEN_EXPIRES_ON` is left blank, none of this runs, and the bot
logs a one-time warning on startup reminding you it's not tracked.

## Removing the claudebot account

If you've moved to the MicroK8s deployment (step 7), `claudebot` isn't doing
any security work anymore and can be deleted. As Administrator:

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
- The real backstop for `tools:full` is whichever isolation you used:
  `claudebot`'s limited account permissions (step 3), or the
  non-root/no-capabilities MicroK8s pod (step 7) — pick one, don't rely on
  the Discord-side confirmation button alone.
- Everything is logged to `logs/bot.log`, including rejected/unauthorized
  attempts and confirm/cancel/timeout decisions.
