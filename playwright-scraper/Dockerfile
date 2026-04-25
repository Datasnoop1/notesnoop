# Use Microsoft's official Playwright image — bundles Chromium and all the
# system libs (libnss3, libgbm, etc.) the headless browser needs. Avoids
# the long apt install dance that a from-scratch python:slim base would
# otherwise need on every rebuild.
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

# Install Python deps. Playwright + Chromium are already in the base image.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code last so changes to server.py don't bust the pip layer cache.
COPY server.py .

# Internal port. nginx not exposed — only reachable on the docker network.
EXPOSE 8000

# Single uvicorn worker is correct: the BrowserContext pool is per-process,
# and we cap concurrency inside the app via an asyncio.Semaphore. Multiple
# uvicorn workers would each launch their own Chromium and blow RAM.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
