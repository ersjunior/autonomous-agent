# Coqui TTS (0.22.x) só publica wheels para Python 3.9–3.11; não há distribuição para 3.12.
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV COQUI_MODEL=tts_models/multilingual/multi-dataset/xtts_v2
ENV COQUI_VOICE_SAMPLE=/voices/reference.wav

RUN mkdir -p /voices

EXPOSE 8002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
