FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# DKIM key store (shared volume in compose); ensure the mount point exists.
RUN mkdir -p /dkim

EXPOSE 8000

# 2 workers + threads is ample for <1k msgs/day plus the internal event API.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", \
     "--access-logfile", "-", "--error-logfile", "-", "app.main:app"]
