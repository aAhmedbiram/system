FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# حل مشكلة قراءة المجلد كحزمة بايثون
RUN touch system_app/__init__.py

RUN mkdir -p logs && chmod 755 logs

EXPOSE 5000

# تشغيل gunicorn من داخل مجلد system_app لضمان إيجاد app.py
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--chdir", "/app/system_app", "app:app", "--workers", "1", "--threads", "2", "--timeout", "120"]