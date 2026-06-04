# SadTalker + FastAPI — requer NVIDIA GPU (CUDA 12.x). Ver README.md.
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV SADTALKER_ROOT=/opt/SadTalker
ENV PYTHONPATH=/opt/SadTalker
ENV AVATAR_VIDEOS_DIR=/data/videos
ENV AVATARS_DIR=/avatars
ENV SADTALKER_SIZE=256
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3-pip \
    python3.10-venv \
    ffmpeg \
    git \
    wget \
    curl \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip

# SadTalker oficial + checkpoints (build longo — ~vários GB)
RUN git clone --depth 1 https://github.com/OpenTalker/SadTalker.git "${SADTALKER_ROOT}" \
    && cd "${SADTALKER_ROOT}" \
    && bash scripts/download_models.sh

COPY requirements.txt install_deps.sh ./
RUN chmod +x install_deps.sh && ./install_deps.sh

COPY app.py .

RUN mkdir -p /data/videos "${AVATARS_DIR}" \
    && cp "${SADTALKER_ROOT}/examples/source_image/happy.png" "${AVATARS_DIR}/default.png"

EXPOSE 8003

# Health exige model_loaded=true (modelos carregados no lifespan)
HEALTHCHECK --interval=30s --timeout=10s --retries=20 --start-period=900s \
  CMD python -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8003/health'); d=json.loads(r.read()); assert d.get('status')=='ok' and d.get('model_loaded') is True and d.get('gpu') is True, d"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
