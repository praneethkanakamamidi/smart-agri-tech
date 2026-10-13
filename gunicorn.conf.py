"""Gunicorn settings for production (`./entrypoint.sh serve`). Override with environment variables."""
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('BACKEND_PORT', '8000')}"
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.getenv("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 8)))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "2000"))  # recycle workers to bound memory growth
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "200"))
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
accesslog = "-" if os.getenv("GUNICORN_ACCESS_LOG", "false").lower() == "true" else None
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
