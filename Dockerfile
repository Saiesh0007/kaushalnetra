# Single-container demo: API + built dashboard + pre-seeded demo database (no ML libraries needed to serve).
# Build the dashboard first (cd dashboard && npm run build) and seed server/var (python scripts/seed_demo.py).
FROM python:3.12-slim
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY common common
COPY server server
COPY configs configs
COPY ml/results ml/results
COPY dashboard/dist dashboard/dist
ENV KNETRA_VAR=/app/server/var
EXPOSE 7860
CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "7860"]
