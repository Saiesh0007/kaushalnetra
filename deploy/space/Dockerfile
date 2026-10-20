# Hugging Face Docker Space: API + built dashboard + pre-seeded demo database + the edge agent for live runs.
# Assembled by scripts/build_space.py; build context is deploy/space/build.
FROM python:3.12-slim

# OpenCV (pulled in by ultralytics) needs these at import time
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
# Spaces run the container as uid 1000; the database and the edge outbox are written under /app
RUN useradd -m -u 1000 user
WORKDIR /app

RUN pip install --no-cache-dir torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
USER user
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    KNETRA_VAR=/app/server/var \
    KNETRA_SELF_URL=http://127.0.0.1:7860 \
    YOLO_CONFIG_DIR=/tmp/ultralytics
EXPOSE 7860
CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "7860"]
