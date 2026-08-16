# Linux image for "Claudiu Remote", built for deployment on a Kubernetes
# cluster (e.g. MicroK8s). See README.md, "MicroK8s deployment" section.

FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates git && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Claude Code CLI. Adjust the package name/version if you installed it
# differently elsewhere.
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

RUN useradd --create-home --uid 10001 claudebot && \
    mkdir -p /app/logs && chown -R claudebot:claudebot /app
USER claudebot

ENTRYPOINT ["python", "bot.py"]
