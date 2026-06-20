#!/bin/bash
# Run this BEFORE taking the image into the air-gapped environment.
# It pre-downloads all npm packages into the Docker layer.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Building air-gapped OpenForge image..."
echo "Requires internet access. Run this before air-gapped deployment."
docker build -f docker/Dockerfile -t openforge-pcb:airgapped .
echo "Done. Transfer openforge-pcb:airgapped.tar to air-gapped environment."
docker save openforge-pcb:airgapped -o openforge-pcb:airgapped.tar
