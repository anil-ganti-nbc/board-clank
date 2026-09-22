# Board Clank Foundation 0 — non-root, read-only health, no webhook secrets.
FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134

ARG GIT_REVISION=unknown
LABEL clank.id="board-clank" \
      org.opencontainers.image.revision="${GIT_REVISION}" \
      org.opencontainers.image.source="https://github.com/anil-ganti-nbc/board-clank"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BOARD_CLANK_RELEASE_CHANNEL=foundation-0 \
    BOARD_CLANK_SOURCE_REVISION=${GIT_REVISION} \
    BOARD_CLANK_DATA_DIR=/app/data

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin clank

COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
COPY config ./config
COPY migrations ./migrations
COPY fixtures ./fixtures
COPY docs ./docs

RUN pip install -r requirements.lock \
    && pip install --no-deps . \
    && mkdir -p /app/data \
    && chown -R clank:clank /app

USER clank

HEALTHCHECK --interval=60s --timeout=15s --start-period=10s --retries=3 \
    CMD ["board-clank", "health"]

ENTRYPOINT ["board-clank"]
CMD ["health"]
