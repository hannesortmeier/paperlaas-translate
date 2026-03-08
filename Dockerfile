FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libreoffice-writer \
        libsm6 \
        libxext6 \
        libxcb1 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN uv sync --no-dev --no-editable

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "paperlaas_translate.main:app", "--host", "0.0.0.0", "--port", "8001"]
