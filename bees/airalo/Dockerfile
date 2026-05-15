# syntax=docker/dockerfile:1.7

# --- build stage ------------------------------------------------------------
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Build tools needed for wheels (lxml, asyncpg, greenlet, ...).
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

# Build a wheel of the project once so the runtime stage stays slim.
RUN pip install --upgrade pip build \
 && python -m build --wheel --outdir /wheels .


# --- runtime stage ----------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOME=/app \
    # Default config / env paths inside the image (override at run time).
    CONFIG_FILE=/app/config.yaml

WORKDIR ${APP_HOME}

# Minimal runtime deps. Playwright's `--with-deps` installs the rest below
# only if browsers are part of the build.
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
        ca-certificates \
        curl \
        tini \
 && rm -rf /var/lib/apt/lists/*

# Install the project wheel + runtime extras.
COPY --from=builder /wheels/*.whl /tmp/
RUN pip install /tmp/*.whl \
 && rm -f /tmp/*.whl

# Playwright browsers + their system dependencies. Pin to chromium to keep
# the image small; change to `chromium firefox webkit` if you need them all.
RUN playwright install --with-deps chromium

# Project config + .env template. Real secrets should come from runtime env
# vars or a mounted .env (see docker-compose.yml).
COPY config.yaml /app/config.yaml
COPY .env.template /app/.env.template

# Drop privileges. ``app`` owns /app so volume-mounted ``data/`` works.
RUN groupadd --system app \
 && useradd  --system --gid app --home-dir ${APP_HOME} --shell /sbin/nologin app \
 && mkdir -p /app/data \
 && chown -R app:app /app
USER app

EXPOSE 8000

# tini reaps zombies and forwards signals cleanly to the Python process.
ENTRYPOINT ["/usr/bin/tini", "--"]
# Default command: print CLI help. Override at run time, e.g.:
#   docker run --rm <image> run example
#   docker run --rm -p 8000:8000 <image> serve --host 0.0.0.0
CMD ["airalo", "--help"]
