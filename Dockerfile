# syntax=docker/dockerfile:1

# One image, one process: uvicorn serving app.main:app. The test suite ships in
# it too — CI runs pytest inside this exact image, and an image you tested is
# worth more than the few megabytes pytest costs.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Resolved from requirements.txt alone, so this layer survives every change that
# does not touch it.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Nothing in the container needs to write anywhere, so it does not run as root.
RUN useradd --create-home --uid 10001 galka && chown -R galka:galka /app
USER galka

EXPOSE 8000

# Overridden by compose; this is the one that serves traffic. Uvicorn rather
# than gunicorn: /events is an SSE stream held open for the life of a client,
# which a synchronous worker model cannot carry.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
