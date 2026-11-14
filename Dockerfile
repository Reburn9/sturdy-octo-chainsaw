FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt
COPY . .
RUN DJANGO_DEBUG=0 DJANGO_SECRET_KEY=build-only-key-not-used-at-runtime-0000000000000000000000000000 python manage.py collectstatic --noinput \
    && useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser
ENV DJANGO_DEBUG=0 SQLITE_PATH=/app/data/db.sqlite3
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-"]
