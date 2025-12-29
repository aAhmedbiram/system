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
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    postgresql-client \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with better error handling
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt || \
    (echo "Failed to install requirements" && cat requirements.txt && exit 1)

# Copy application code
COPY . .

# Create logs directory with proper permissions
RUN mkdir -p logs && \
    chmod 755 logs

# Expose port
EXPOSE 5000

# Health check endpoint (optional, can be removed if causing issues)
# HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
#     CMD python -c "import socket; s=socket.socket(); s.connect(('localhost', ${PORT:-5000})); s.close()" || exit 1

# Run gunicorn using shell form to handle environment variable
CMD gunicorn system_app.app:app --bind 0.0.0.0:5000 --workers 2 --timeout 120 --access-logfile - --error-logfile -
