# CodeMentor API
#
# Multi-stage so the runtime image carries no build toolchain and no dev
# dependencies. PyroCore is a separate service; this image talks to it over HTTP
# and holds no database of its own.

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# Run as an unprivileged user: a container escape should not land as root.
RUN groupadd --system codementor \
    && useradd --system --gid codementor --home /app codementor

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=codementor:codementor app ./app
COPY --chown=codementor:codementor scripts ./scripts

USER codementor

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# One worker on purpose. The projector runs in-process, so a second worker would
# mean two pollers racing on the same queue. Scale by adding instances only after
# the queue is claimed with a conditional UPDATE.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]