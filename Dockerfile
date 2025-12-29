# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    PYTHONPATH=/app

# Install system dependencies including build essentials for psycopg2
# تم إضافة build-essential و musl-dev لضمان استقرار البناء
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    musl-dev \
    postgresql-client \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p logs && chmod 755 logs

# Expose port
EXPOSE 5000

# Run gunicorn - Direct path to app:app
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]