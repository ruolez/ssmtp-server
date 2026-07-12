#!/bin/sh
# Render runtime config from env, then launch Haraka.
set -e

CONFIG=/app/config
HOSTNAME="${MAIL_HOSTNAME:-mail.example.com}"
# caddy_data volume, mounted read-only; Caddy's storage root is /data in its
# own container, so certificates land under <mount>/caddy/certificates/.
CADDY_CERTS=/caddy/caddy/certificates

# Hostname used in HELO/EHLO and the SMTP banner.
echo "$HOSTNAME" > "$CONFIG/me"

# Submission TLS (587 STARTTLS / 465 implicit) reuses the Let's Encrypt
# certificate Caddy obtains for the dashboard. SMTP clients verify the chain,
# so a self-signed cert makes them abort the handshake before AUTH.
find_caddy_cert() {
  find "$CADDY_CERTS" -type f -name "$HOSTNAME.crt" 2>/dev/null | head -1
}

install_caddy_cert() {
  crt=$(find_caddy_cert)
  [ -n "$crt" ] && [ -f "${crt%.crt}.key" ] || return 1
  cp "$crt" "$CONFIG/tls_cert.pem"
  cp "${crt%.crt}.key" "$CONFIG/tls_key.pem"
}

if install_caddy_cert; then
  echo "Submission TLS: using Let's Encrypt certificate for $HOSTNAME (shared from Caddy)"
else
  # Bootstrap only: lets Haraka start before Caddy's first issuance. The
  # watcher below swaps in the real certificate as soon as it appears.
  echo "Submission TLS: no Caddy certificate for $HOSTNAME yet; using temporary self-signed cert"
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CONFIG/tls_key.pem" \
    -out "$CONFIG/tls_cert.pem" \
    -days 3650 -subj "/CN=$HOSTNAME" >/dev/null 2>&1
fi

# Haraka only reads the cert at startup, so when Caddy issues or renews one,
# exit and let docker's restart policy bring us back up on the fresh cert.
(
  while true; do
    sleep 600
    crt=$(find_caddy_cert)
    [ -n "$crt" ] || continue
    if ! cmp -s "$crt" "$CONFIG/tls_cert.pem"; then
      echo "Submission TLS: certificate changed; restarting to pick it up"
      kill 1
    fi
  done
) &

exec ./node_modules/.bin/haraka -c /app
