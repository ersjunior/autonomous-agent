#!/bin/sh
set -eux

pip install --no-cache-dir -r requirements.txt

# Remove wheels CUDA que o TTS puxa; reinstala só CPU.
pip uninstall -y torch torchaudio triton 2>/dev/null || true
pip freeze | grep -i '^nvidia-' | cut -d= -f1 | while read -r pkg; do
  pip uninstall -y "$pkg" 2>/dev/null || true
done

pip install --no-cache-dir torch==2.5.1 torchaudio==2.5.1 \
  --index-url https://download.pytorch.org/whl/cpu

python -c "import torch; import torchaudio; assert not torch.cuda.is_available(); print('PyTorch CPU OK')"
