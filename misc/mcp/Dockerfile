# The MCP server over Streamable HTTP. Build from the repository root, so the
# wheel can bundle the README, the notes and the benchmarks:
#
#   docker build -f misc/mcp/Dockerfile -t cpu-perf .
#   docker run -p 8000:8000 -v cpu-perf-data:/data cpu-perf
#
# The image carries no crawled text: the running container builds its source
# library into the /data volume.

FROM python:3.12-slim AS build
WORKDIR /src
COPY README.md CONTRIBUTING.md LICENSE ./
COPY .github ./.github
COPY misc ./misc
ARG GIT_COMMIT=unknown
RUN CPU_PERF_COMMIT=$GIT_COMMIT pip wheel --no-cache-dir --no-deps -w /dist ./misc/mcp

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 mcp && mkdir -p /data && chown mcp /data
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
USER mcp
ENV CPU_PERF_DATA_DIR=/data \
    CPU_PERF_HOST=0.0.0.0 \
    CPU_PERF_PORT=8000 \
    HF_HOME=/data/huggingface \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1
ENTRYPOINT ["cpu-perf", "serve", "--transport", "http"]
