#!/bin/bash
# petal-build — rebuild OWUI frontend and re-seat the editable install 🌸
set -e
cd ~/Gardens/petal-open-webui

echo "🌸 building frontend..."
npm run build

echo "🌸 re-seating editable install..."
source ~/.venvs/openwebui/bin/activate
python -m pip install -e . --quiet

echo "✨ done~ restart open-webui serve to pick up changes"
