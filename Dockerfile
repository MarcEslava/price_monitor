FROM python:3.11-slim

# PYTHONUNBUFFERED so scrapyd/spider logs stream out immediately (docker logs).
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl is used by the entrypoint healthcheck loop.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Put the Scrapyd config at the global path that's read regardless of the
# daemon's working directory. This lets the entrypoint start scrapyd from a
# neutral dir (not /app), so scrapyd doesn't pick up the project's scrapy.cfg
# [settings] section and expose a phantom "default" project from source.
RUN mkdir -p /etc/scrapyd \
 && cp /app/scrapyd.conf /etc/scrapyd/scrapyd.conf

# Normalise line endings and make the entrypoint executable (guards against the
# script being checked out / copied from Windows with CRLF).
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh \
 && chmod +x /app/docker-entrypoint.sh

EXPOSE 6800

ENTRYPOINT ["/app/docker-entrypoint.sh"]
