#!/bin/sh
set -eux

pip install --no-cache-dir -r requirements.txt

# TTS pode puxar torch CPU; garantir build CUDA (libs embarcadas no wheel cu124).
pip uninstall -y torch torchaudio triton 2>/dev/null || true
pip install --no-cache-dir torch==2.5.1 torchaudio==2.5.1 \
  --index-url https://download.pytorch.org/whl/cu124

python -c "import torch; print('torch', torch.__version__, 'cuda_build', torch.version.cuda)"
