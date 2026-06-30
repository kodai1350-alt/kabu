FROM python:3.12-slim

WORKDIR /app

# 依存ライブラリ
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt flask gunicorn

# ソースコード
COPY . .

ENV PYTHONIOENCODING=utf-8
ENV PORT=8080

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "600", "--workers", "1", "cloud_server:app"]
