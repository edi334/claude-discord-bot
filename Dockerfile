# Windows container image for "Claudiu Remote". Build/run this on the
# Windows Server 2025 host with `--isolation=hyperv` so the container has no
# visibility into the host filesystem beyond the one volume mounted at
# C:\workdir. See README.md, "Container deployment" section.

FROM python:3.12-windowsservercore-ltsc2025
# If this exact tag isn't published yet, use the closest windowsservercore
# tag available (e.g. -ltsc2022) — with --isolation=hyperv the container
# kernel doesn't need to match the host build, unlike process isolation.

SHELL ["powershell", "-NoProfile", "-Command"]

# Node.js, needed for the Claude Code CLI (npm package). Bump the version
# below if you want a newer Node.
RUN Invoke-WebRequest -Uri https://nodejs.org/dist/v20.17.0/node-v20.17.0-x64.msi -OutFile C:\node.msi
RUN Start-Process msiexec.exe -ArgumentList '/i C:\node.msi /quiet /norestart' -Wait
RUN Remove-Item C:\node.msi
RUN setx PATH "$env:PATH;C:\Program Files\nodejs" /M

# Claude Code CLI. Adjust the package name/version if you installed it
# differently on the host.
RUN npm install -g @anthropic-ai/claude-code

WORKDIR C:\app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

ENTRYPOINT ["python", "bot.py"]
