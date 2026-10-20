# Hosted demo: API + built dashboard + pre-seeded demo database + the edge agent (ONNX) for live runs.
# Assembled by scripts/build_web.py; build context is deploy/web/build. Fits a free 512 MB instance.
FROM python:3.12-slim

# run as an unprivileged user; the database and the edge outbox are written under /app
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
USER user
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    KNETRA_VAR=/app/server/var \
    KNETRA_DETECTOR=yolo11n.onnx \
    OMP_NUM_THREADS=1
EXPOSE 10000
# hosts such as Render pass the port in $PORT; live runs talk to the server on that same port
CMD ["sh", "-c", "export KNETRA_SELF_URL=http://127.0.0.1:${PORT:-10000}; exec uvicorn server.app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
