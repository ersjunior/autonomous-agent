# SadTalker (GPU)

Serviço REST local de talking-head (imagem + áudio → MP4). **Requer NVIDIA GPU** e [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

## GPU no Compose

A stack base (`docker-compose.yml`) reserva GPU para **ollama** e **sadtalker** via `deploy.resources.reservations.devices` (driver `nvidia`). Em máquinas **sem** GPU, `docker compose up` pode falhar nesses serviços — use uma máquina com drivers NVIDIA ou comente os blocos `deploy` localmente.

- **Coqui TTS**: permanece CPU (`install_deps.sh` remove wheels CUDA). `# TODO: GPU opcional para Coqui`
- **faster-whisper**: CPU por padrão (`WHISPER_DEVICE=cpu`). `# TODO: GPU opcional para Whisper`

## Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| GET | `/health` | `model_loaded`, `gpu`, `device` |
| POST | `/generate` | multipart `image` + `audio` → `{ video_filename, status }` |

## Volumes

- `/data/videos` — MP4 gerados (`avatar_video` no compose)
- `/avatars` — imagens de rosto (ex.: `default.png` montado de `infra/docker/sadtalker/avatars/`)

## Build (longo)

```bash
docker compose --env-file .env -f infra/docker/docker-compose.yml build sadtalker
```

Checkpoints e PyTorch CUDA são baixados/instalados no build (~vários GB).

## Validação

```bash
curl -s http://localhost:8003/health | jq
docker exec autonomous-agent-sadtalker python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```
