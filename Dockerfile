FROM python:3.12-slim

# Cap glibc malloc arenas. The default (~8×CPU) lets each worker thread keep its
# own up-to-64MB arena that Python frees but glibc never returns to the OS, so RSS
# ratchets up after every pandas/numpy/yfinance fetch cycle (the 15-min market
# refresh + per-request /api/quotes). 2 arenas keeps fragmentation flat at a small
# throughput cost. Applies to the uvicorn workers AND the cron execs in this
# container.
ENV MALLOC_ARENA_MAX=2

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Commit this image was built from, surfaced by GET /api/version so a redeploy
# can be confirmed without SSH. Optional: build_info also fingerprints the
# copied source at runtime, which needs no build wiring, so leaving this empty
# only costs the commit hash. Pass it through Dokploy's build args
# (GIT_SHA=<sha>) or `docker build --build-arg GIT_SHA=$(git rev-parse HEAD)`.
ARG GIT_SHA=""
ENV GIT_SHA=$GIT_SHA

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
