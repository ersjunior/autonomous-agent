#!/bin/sh
set -eux

# PyTorch + torchvision compatíveis com basicsr/gfpgan (SadTalker requirements)
# cu121 roda em hosts com driver CUDA 12.x (ex.: RTX 4090)
pip install --no-cache-dir \
  torch==2.1.2 \
  torchvision==0.16.2 \
  torchaudio==2.1.2 \
  --index-url https://download.pytorch.org/whl/cu121

pip install --no-cache-dir -r /opt/SadTalker/requirements.txt

# API
pip install --no-cache-dir -r /app/requirements.txt

python -c "import torch, torchvision; print('torch', torch.__version__, 'cuda', torch.cuda.is_available()); print('torchvision', torchvision.__version__)"
