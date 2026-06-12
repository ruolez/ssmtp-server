#!/bin/sh
# Render runtime config from env, then launch Haraka.
set -e

CONFIG=/app/config
HOSTNAME="${MAIL_HOSTNAME:-mail.example.com}"

# Hostname used in HELO/EHLO and the SMTP banner.
echo "$HOSTNAME" > "$CONFIG/me"

# Self-signed cert for submission TLS (587 STARTTLS / 465 implicit). Internal
# apps connect to this; the public dashboard cert is handled separately by Caddy.
if [ ! -f "$CONFIG/tls_cert.pem" ]; then
  echo "Generating self-signed TLS certificate for $HOSTNAME ..."
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CONFIG/tls_key.pem" \
    -out "$CONFIG/tls_cert.pem" \
    -days 3650 -subj "/CN=$HOSTNAME" >/dev/null 2>&1
fi

exec ./node_modules/.bin/haraka -c /app
