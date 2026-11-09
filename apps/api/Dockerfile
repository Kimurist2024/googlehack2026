# apps/api をビルドの起点にする: gcloud run deploy mushitori --source apps/api
# 画面（apps/web）は Firebase Hosting が配るので、イメージには入れない
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt requirements-gcp.txt ./
RUN pip install --no-cache-dir -r requirements-gcp.txt
COPY app ./app
COPY qgen ./qgen

RUN useradd --create-home --uid 10001 appuser
USER appuser
# Cloud Run は PORT を環境変数で渡す
# server ヘッダーで実装と版を明かさない
CMD ["sh", "-c", "exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port ${PORT:-8080} --no-server-header"]
