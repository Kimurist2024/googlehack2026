FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt requirements-gcp.txt ./
RUN pip install --no-cache-dir -r requirements-gcp.txt
COPY app ./app
COPY qgen ./qgen
COPY web ./web

RUN useradd --create-home --uid 10001 appuser
USER appuser
# Cloud Run は PORT を環境変数で渡す
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
