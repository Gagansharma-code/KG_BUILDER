# OpenForge PCB Builder — air-gapped deployment image
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY configs ./configs

RUN pip install --no-cache-dir -e .

# Install Node.js LTS
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs

# Pre-cache tscircuit CLI for air-gapped operation
RUN npm install -g @tscircuit/cli

# Verify installation
RUN npx @tscircuit/cli --version

# Set npm offline mode for production runs
# (prevents network calls in air-gapped environment)
ENV NPM_CONFIG_PREFER_OFFLINE=true

CMD ["python", "-c", "import src.output; print('OpenForge output pipeline ready')"]
