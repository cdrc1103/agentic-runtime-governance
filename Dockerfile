# Reference image for the decision service (sample configuration, not production-hardened).
# Build:  docker build -t arg-service .
# Run:    docker run --rm -p 8080:8080 \
#           -e ARG_TOKENS='{"change-me":{"principal":"ops","roles":["admin","submit"]}}' \
#           -e ARG_TOKEN_KEY="$(cat token-key.pem)" arg-service
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --extra service --extra gateway

FROM python:3.12-slim
RUN useradd --system --uid 10001 --create-home arg
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
COPY config ./config
ENV PATH="/app/.venv/bin:$PATH" ARG_CONFIG=/app/config/runtime.yaml PYTHONUNBUFFERED=1
USER arg
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["uvicorn", "arg.service.main:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8080"]
