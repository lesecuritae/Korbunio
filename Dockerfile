ARG PYTHON_BASE=python:3.13-alpine@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d

FROM ${PYTHON_BASE} AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN /opt/venv/bin/pip install --upgrade "pip>=26.2" "setuptools>=78.1.1" wheel \
    && /opt/venv/bin/pip install . \
    && /opt/venv/bin/pip uninstall -y pip setuptools wheel \
    && find /opt/venv -type d -name __pycache__ -prune -exec rm -r {} +

FROM ${PYTHON_BASE} AS runtime-rootfs
ARG PYTHON_BASE
RUN apk upgrade --no-cache \
    && apk add --no-cache chromium ca-certificates curl dumb-init tzdata \
    && python -m pip uninstall -y pip setuptools wheel \
    && rm -rf /root/.cache /usr/local/lib/python3.13/ensurepip
COPY --from=builder /opt/venv /opt/venv
RUN addgroup -S -g 10001 korbklar \
    && adduser -S -D -H -u 10001 -G korbklar korbklar \
    && mkdir -p /home/korbklar \
    && mkdir -p /data /app \
    && chown -R korbklar:korbklar /home/korbklar /data /app

FROM scratch AS final
ARG PYTHON_BASE
ARG APP_VERSION=0.1.8
COPY --from=runtime-rootfs / /
LABEL org.opencontainers.image.source="https://github.com/lesecuritae/KorbKlar" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.base.name="${PYTHON_BASE}"
# trivy:ignore:AVD-DS-0031 -- this is a path to a runtime-generated file, not secret material.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    SUPERMARKT_DATA_DIR=/data \
    SUPERMARKT_CACHE_DB=/data/supermarkt-cache.sqlite3 \
    SUPERMARKT_SIGNING_SECRET_FILE=/data/.signing-secret \
    SUPERMARKT_IMAGE_CACHE_DIR=/data/supermarkt-images \
    SUPERMARKT_KAUFLAND_CACHE_DIR=/data/kaufland \
    SUPERMARKT_REWE_CACHE_DIR=/data/rewe
WORKDIR /app
USER 10001
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=12 CMD ["curl", "--fail", "--silent", "http://127.0.0.1:8000/health"]
ENTRYPOINT ["dumb-init", "--"]
CMD ["uvicorn", "supermarkt.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
