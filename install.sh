#!/usr/bin/env bash
#
# ssmtp-server installer for Ubuntu (24.04 / 26.04).
# Install / Update / Remove a self-hosted outbound SMTP relay + web console.
#
set -euo pipefail

REPO_URL="https://github.com/ruolez/ssmtp-server.git"
INSTALL_DIR="/opt/ssmtp-server"
ENV_FILE="$INSTALL_DIR/.env"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
print_header()  { echo -e "\n${BLUE}========================================${NC}\n${BLUE}$1${NC}\n${BLUE}========================================${NC}\n"; }
print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_error()   { echo -e "${RED}✗ $1${NC}"; }
print_warning() { echo -e "${YELLOW}! $1${NC}"; }
print_info()    { echo -e "  $1"; }

require_root() {
  if [ "$EUID" -ne 0 ]; then
    print_error "Please run as root (sudo bash install.sh)"
    exit 1
  fi
}

rand() { head -c "${1:-32}" /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c "${1:-32}"; }

# Force the local checkout to match the canonical repo exactly. Re-points the
# origin at REPO_URL (in case it ever drifted) and hard-resets to origin/main.
# Safe for our layout: .env, db backups and data volumes are gitignored and are
# never touched by the reset.
sync_repo() {
  git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL" 2>/dev/null \
    || git -C "$INSTALL_DIR" remote add origin "$REPO_URL"
  git -C "$INSTALL_DIR" fetch origin main
  git -C "$INSTALL_DIR" reset --hard origin/main
}

detect_ip() {
  local ip
  ip=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'src \K\S+' || true)
  [ -z "$ip" ] && ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo "$ip"
}

# ---------------------------------------------------------------------------
install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    print_success "Docker already installed"
    return
  fi
  print_info "Installing Docker..."
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg lsb-release git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  print_success "Docker installed"
}

configure_firewall() {
  command -v ufw >/dev/null 2>&1 || { print_info "ufw not present; skipping firewall config"; return; }
  print_info "Opening firewall ports (22, 25, 80, 443, 465, 587)..."
  ufw allow 22/tcp   >/dev/null 2>&1 || true
  ufw allow 25/tcp   >/dev/null 2>&1 || true   # outbound delivery + relay
  ufw allow 80/tcp   >/dev/null 2>&1 || true   # ACME HTTP challenge
  ufw allow 443/tcp  >/dev/null 2>&1 || true   # dashboard (TLS)
  ufw allow 465/tcp  >/dev/null 2>&1 || true   # submission (implicit TLS)
  ufw allow 587/tcp  >/dev/null 2>&1 || true   # submission (STARTTLS)
  print_success "Firewall rules applied (ufw)"
}

# ---------------------------------------------------------------------------
prompt_config() {
  print_header "Configuration"

  local default_ip; default_ip=$(detect_ip)
  read -rp "Public IPv4 of this server [$default_ip]: " SERVER_IP
  SERVER_IP=${SERVER_IP:-$default_ip}

  read -rp "Sending domain (e.g. example.com): " MAIL_DOMAIN
  while [ -z "${MAIL_DOMAIN:-}" ]; do read -rp "  Sending domain is required: " MAIL_DOMAIN; done

  read -rp "Mail hostname [mail.$MAIL_DOMAIN]: " MAIL_HOSTNAME
  MAIL_HOSTNAME=${MAIL_HOSTNAME:-mail.$MAIL_DOMAIN}

  read -rp "Admin username for the web console [admin]: " ADMIN_USERNAME
  ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
  read -rsp "Admin password: " ADMIN_PASSWORD; echo
  while [ -z "${ADMIN_PASSWORD:-}" ]; do read -rsp "  Password is required: " ADMIN_PASSWORD; echo; done

  read -rp "Email for Let's Encrypt notices [admin@$MAIL_DOMAIN]: " ACME_EMAIL
  ACME_EMAIL=${ACME_EMAIL:-admin@$MAIL_DOMAIN}

  echo
  print_info "TLS certificate mode:"
  print_info "  1) Production  — real trusted certs (use for go-live)"
  print_info "  2) Staging     — test certs, high rate limits (use while testing DNS)"
  read -rp "Choose [1/2, default 2]: " acme_choice
  if [ "${acme_choice:-2}" = "1" ]; then
    ACME_CA="https://acme-v02.api.letsencrypt.org/directory"
  else
    ACME_CA="https://acme-staging-v02.api.letsencrypt.org/directory"
  fi
}

write_env() {
  # Preserve generated secrets across re-installs. POSTGRES_PASSWORD especially:
  # Postgres only applies it on first init, so regenerating it would lock the
  # app out of the existing database. SECRET_KEY/INTERNAL_SECRET are kept too so
  # we don't invalidate sessions or desync the Haraka<->web event secret.
  local secret_key="" internal_secret="" pg_password=""
  if [ -f "$ENV_FILE" ]; then
    secret_key=$(grep '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- || true)
    internal_secret=$(grep '^INTERNAL_SECRET=' "$ENV_FILE" | cut -d= -f2- || true)
    pg_password=$(grep '^POSTGRES_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)
  fi
  [ -n "$secret_key" ] || secret_key=$(rand 48)
  [ -n "$internal_secret" ] || internal_secret=$(rand 48)
  [ -n "$pg_password" ] || pg_password=$(rand 32)

  cat > "$ENV_FILE" <<EOF
# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
MAIL_HOSTNAME=$MAIL_HOSTNAME
MAIL_DOMAIN=$MAIL_DOMAIN
SERVER_IP=$SERVER_IP

ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD=$ADMIN_PASSWORD
SECRET_KEY=$secret_key
INTERNAL_SECRET=$internal_secret

POSTGRES_USER=ssmtp
POSTGRES_PASSWORD=$pg_password
POSTGRES_DB=ssmtp
POSTGRES_HOST=db
POSTGRES_PORT=5432

ACME_EMAIL=$ACME_EMAIL
ACME_CA=$ACME_CA

WEB_DEV_PORT=8025
EOF
  chmod 600 "$ENV_FILE"
  print_success "Wrote $ENV_FILE"
}

wait_healthy() {
  print_info "Waiting for services to become healthy..."
  for _ in $(seq 1 30); do
    if docker compose -f "$INSTALL_DIR/docker-compose.yml" exec -T web \
         python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)" >/dev/null 2>&1; then
      print_success "Web console is up"
      return 0
    fi
    sleep 2
  done
  print_warning "Services did not report healthy in time; check 'docker compose logs'"
}

print_dns_records() {
  print_header "Publish these DNS records for $MAIL_DOMAIN"
  print_warning "PTR (reverse DNS) is set in your VPS provider's panel: $SERVER_IP -> $MAIL_HOSTNAME"
  echo
  docker compose -f "$INSTALL_DIR/docker-compose.yml" exec -T web python - <<'PY' 2>/dev/null || print_warning "Open https://$MAIL_HOSTNAME/dns to view records."
import os
from app import deliverability as d
domain = os.environ["MAIL_DOMAIN"]
d.ensure_dkim_key(domain)
for r in d.build_dns_records(domain, os.environ["MAIL_HOSTNAME"], os.environ["SERVER_IP"]):
    print(f"  [{r['type']:4}] {r['fqdn']}")
    print(f"         {r['value']}\n")
PY
  print_info "You can also manage and verify these at: https://$MAIL_HOSTNAME/dns"
}

# ---------------------------------------------------------------------------
do_install() {
  print_header "Install ssmtp-server"
  install_docker

  if [ -d "$INSTALL_DIR/.git" ]; then
    print_info "Existing install found; syncing with $REPO_URL ..."
    sync_repo
  else
    print_info "Cloning $REPO_URL ..."
    git clone "$REPO_URL" "$INSTALL_DIR"
  fi

  prompt_config
  write_env
  configure_firewall

  print_info "Building and starting containers (first build may take a few minutes)..."
  docker compose -f "$INSTALL_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d --build

  wait_healthy
  print_dns_records

  print_header "Done"
  print_success "Console:   https://$MAIL_HOSTNAME  (login: $ADMIN_USERNAME)"
  print_success "Submission: $MAIL_HOSTNAME:587 (STARTTLS) or :465 (TLS), per-app credentials"
  print_warning "Publish the DNS records above and set PTR before sending real mail."
}

do_update() {
  print_header "Update ssmtp-server"
  [ -d "$INSTALL_DIR/.git" ] || { print_error "Not installed at $INSTALL_DIR"; exit 1; }

  # Back up the database only. The Caddy cert volume is intentionally left
  # untouched so TLS certs are preserved (avoids Let's Encrypt rate limits).
  local stamp backup
  stamp=$(date +%Y%m%d-%H%M%S)
  backup="$INSTALL_DIR/db-backup-$stamp.sql"
  print_info "Backing up database to $backup ..."
  if docker compose -f "$INSTALL_DIR/docker-compose.yml" exec -T db \
       pg_dump -U ssmtp ssmtp > "$backup" 2>/dev/null; then
    print_success "Database backed up"
  else
    print_warning "Could not back up database (continuing)"
  fi

  print_info "Fetching latest code from $REPO_URL ..."
  sync_repo

  print_info "Rebuilding app containers (cert volume preserved)..."
  docker compose -f "$INSTALL_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d --build

  wait_healthy
  print_success "Update complete. TLS certificates were preserved."
}

do_remove() {
  print_header "Remove ssmtp-server"
  [ -d "$INSTALL_DIR" ] || { print_error "Not installed"; exit 1; }

  read -rp "Stop and remove containers? [y/N]: " yn
  [[ "${yn:-N}" =~ ^[Yy]$ ]] || { print_info "Aborted"; exit 0; }

  echo
  print_warning "Deleting volumes also destroys the database AND the TLS certificates."
  print_warning "If you reinstall later with the same domain, deleted certs count against"
  print_warning "Let's Encrypt rate limits. Keep volumes unless you are fully decommissioning."
  read -rp "Delete ALL volumes (database + certs + DKIM keys)? [y/N]: " delvol

  if [[ "${delvol:-N}" =~ ^[Yy]$ ]]; then
    docker compose -f "$INSTALL_DIR/docker-compose.yml" --env-file "$ENV_FILE" down -v
    print_success "Containers and volumes removed"
  else
    docker compose -f "$INSTALL_DIR/docker-compose.yml" --env-file "$ENV_FILE" down
    print_success "Containers removed; volumes (db, certs, DKIM) kept"
  fi

  read -rp "Also delete $INSTALL_DIR (source + .env)? [y/N]: " deldir
  if [[ "${deldir:-N}" =~ ^[Yy]$ ]]; then
    rm -rf "$INSTALL_DIR"
    print_success "Removed $INSTALL_DIR"
  fi
}

# ---------------------------------------------------------------------------
main() {
  require_root
  print_header "ssmtp-server — outbound SMTP relay"
  echo "  1) Install"
  echo "  2) Update  (preserves DB + TLS certs)"
  echo "  3) Remove"
  echo "  4) Exit"
  echo
  read -rp "Choose an option [1-4]: " choice
  case "${choice:-4}" in
    1) do_install ;;
    2) do_update ;;
    3) do_remove ;;
    *) print_info "Bye"; exit 0 ;;
  esac
}

main "$@"
