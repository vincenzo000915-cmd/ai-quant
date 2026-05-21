FROM python:3.11-slim

WORKDIR /app

# Phase 4: git for GitHub crawler (clones strategy repos)
# Phase 11.5.3.1: nodejs + npm + @anthropic-ai/claude-code
#   admin 走 host /root/.claude OAuth (Claude Pro/Max 訂閱)，免 API token 費
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY run.py .
COPY app/ app/
# Copy pre-built frontend
COPY frontend_build/ frontend/build/

RUN mkdir -p /app/app/tasks /app/app/services && touch /app/app/tasks/__init__.py /app/app/services/__init__.py

CMD ["gunicorn", "-k", "sync", "-w", "2", "-t", "30", "-b", "0.0.0.0:5000", "run:app"]
