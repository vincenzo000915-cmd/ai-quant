FROM python:3.11-slim

WORKDIR /app

# git: required by Phase 4 GitHub crawler (clones strategy repos)
RUN apt-get update && apt-get install -y --no-install-recommends git \
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
