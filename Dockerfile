FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/workmate-matplotlib \
    WORKMATE_DEMO_DIR=/tmp/workmate-demo \
    WORKMATE_DEMO_SECURE_COOKIE=1
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-render.txt ./
RUN pip install --no-cache-dir -r requirements-render.txt
COPY workmate ./workmate
RUN useradd --create-home --uid 10001 workmate
USER workmate
EXPOSE 10000
CMD ["sh", "-c", "python -m uvicorn workmate.demo:create_demo_app --factory --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --no-access-log"]
