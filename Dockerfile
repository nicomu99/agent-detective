FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# sort of like mkdir -p /app && cd /app; else everything is in /
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

ENV UV_NO_SYNC=1

RUN useradd --create-home appuser
USER appuser

EXPOSE 8080
CMD ["uv", "run", "uvicorn", "app.main:main_app", "--host", "0.0.0.0", "--port", "8080"]