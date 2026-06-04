# Coqui TTS (0.22.x) só publica wheels para Python 3.9–3.11; não há distribuição para 3.12.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt install_deps.sh ./
RUN chmod +x install_deps.sh && ./install_deps.sh

COPY app.py .

ENV COQUI_TOS_AGREED=1
ENV COQUI_MODEL=tts_models/multilingual/multi-dataset/xtts_v2
ENV COQUI_VOICE_SAMPLE=/voices/reference.wav
ENV CUDA_VISIBLE_DEVICES=

RUN mkdir -p /voices

# Pré-baixa XTTS-v2 na imagem (~2 GB) — TOS automático via COQUI_TOS_AGREED.
RUN python -c "\
import os; \
os.environ.setdefault('COQUI_TOS_AGREED', '1'); \
from TTS.utils.manage import ModelManager; \
ModelManager().download_model('tts_models/multilingual/multi-dataset/xtts_v2'); \
print('Model download OK')"

EXPOSE 8002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
