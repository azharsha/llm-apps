# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY soctriage/ ./soctriage/

RUN pip install --no-cache-dir build && \
    python -m build --wheel --outdir dist/

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="SD Move"
LABEL description="SoCTriage — Linux kernel / SoC crash diagnostic tool"
LABEL version="1.0.0"

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/soctriage-*.whl[llm] && \
    rm -f /tmp/*.whl

RUN useradd -m -u 1000 soctriage
USER soctriage

WORKDIR /logs
ENTRYPOINT ["soctriage"]
CMD ["--help"]
