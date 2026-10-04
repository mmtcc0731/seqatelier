FROM node:24-bookworm-slim AS viewer
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS builder
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
COPY --from=viewer /build/frontend/dist/ src/seqatelier/web_assets/
RUN pip install --no-cache-dir uv==0.11.28 \
    && uv export --frozen --no-dev --extra cloud --no-emit-project --format requirements-txt --output-file requirements.txt \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.13-slim
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels "seqatelier[cloud]" \
    && rm -rf /wheels \
    && useradd --create-home --uid 10001 workspace \
    && mkdir -p /data /locks \
    && chown workspace:workspace /data /locks
USER workspace
ENV SEQATELIER_WORKSPACE=/data SEQATELIER_CACHE_HOME=/locks PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8765 8766 10000
ENTRYPOINT ["seqatelier"]
CMD ["host", "--allow-writes"]
