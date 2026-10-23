FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd -m appuser && mkdir -p /app/outputs && chown -R appuser /app
USER appuser

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"7860\")}/_stcore/health')" || exit 1

CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-7860} --server.address=0.0.0.0"]
