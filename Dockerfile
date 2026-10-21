FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/.data
COPY requirements.lock ./
RUN --mount=type=secret,id=pip_ca_bundle \
    if [ -f /run/secrets/pip_ca_bundle ]; then export PIP_CERT=/run/secrets/pip_ca_bundle; fi; \
    pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md ./
COPY app ./app
RUN chmod -R a+rX /app/app && useradd --create-home --uid 10001 planner && mkdir -p /app/.data && chown planner:planner /app/.data
USER planner
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
