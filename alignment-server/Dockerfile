# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm AS native-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# Build only the CTC/text package. Its default dependency graph includes PyTorch,
# which the lightweight runtime intentionally does not import or need.
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels \
    "git+https://github.com/michsethowusu/fast-forced-aligner.git@84cc35846489f5b1567840bbd6e0759204685536"

FROM python:3.11-slim-bookworm AS model-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.14.1
RUN python -m pip install --no-cache-dir ctranslate2==4.8.3 numpy==2.4.6 transformers==5.19.0
ARG MODEL_ID=MahmoudAshraf/mms-300m-1130-forced-aligner
ARG MODEL_REVISION=49402e9577b1158620820667c218cd494cc44486
ENV MODEL_ID=${MODEL_ID} MODEL_REVISION=${MODEL_REVISION} \
    HF_HUB_DISABLE_XET=1 OMP_NUM_THREADS=2
COPY docker/build_model.py /build_model.py
RUN python /build_model.py

FROM python:3.11-slim-bookworm AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    ALIGNMENT_HOST=0.0.0.0 ALIGNMENT_PORT=8000 \
    ALIGNMENT_WORKERS=1 ALIGNMENT_CPU_THREADS=2 \
    ALIGNMENT_WINDOW_SECONDS=10 ALIGNMENT_BATCH_SIZE=1 \
    ALIGNMENT_MAX_QUEUED=4 ALIGNMENT_QUEUE_TIMEOUT=600
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 alignment \
    && useradd --uid 10001 --gid alignment --create-home alignment \
    && mkdir -p /data/audio \
    && chown alignment:alignment /data/audio
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY --from=native-build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-deps /wheels/*.whl \
    && rm -rf /wheels
COPY --from=model-build --chown=alignment:alignment /model /app/.cache/mms-300m-ct2-int8
COPY --chown=alignment:alignment *.py ./
COPY --chown=alignment:alignment tests/ ./tests/
COPY --chown=alignment:alignment docker/healthcheck.py ./docker/healthcheck.py
USER alignment
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "docker/healthcheck.py"]
CMD ["python", "alignment_server.py"]
