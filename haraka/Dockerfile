FROM node:20-bookworm-slim

# openssl: bootstrap self-signed cert used only until Caddy's first Let's
# Encrypt issuance (entrypoint.sh swaps in the real cert).
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY config/ ./config/
COPY plugins/ ./plugins/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 25 587 465

ENTRYPOINT ["/entrypoint.sh"]
