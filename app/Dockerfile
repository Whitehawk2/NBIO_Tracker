FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install fastapi "uvicorn[standard]" jinja2 pydantic-settings

COPY nbio/ ./nbio/

EXPOSE 8000

CMD ["uvicorn", "nbio.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
