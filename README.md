# ssmtp-server

A self-hosted **outbound SMTP relay** with a web console for configuration and
monitoring. Your internal apps authenticate and send through it; it signs mail
with DKIM, delivers to the internet, and records the full lifecycle of every
message — submission, queue, each delivery attempt, and final outcome.

Think "small self-hosted SendGrid": no mailboxes, no IMAP — just reliable
authenticated sending plus a dashboard that shows everything in and out.

## Architecture

```
Internal apps ──SMTP AUTH (587 STARTTLS / 465 TLS)──▶ Haraka ──:25──▶ Internet MX
   (per-app credentials)                                │ DKIM-signs, queues, retries
                                                        │
                                              event hooks (in + out)
                                                        ▼
                          POST /internal/events ──▶ Flask API ──▶ PostgreSQL
                                                                     ▲
                                          Flask web console (config + monitoring)
                                                        │
                                          Caddy (auto Let's Encrypt) ──▶ :443
```

| Component | Role |
|-----------|------|
| **Haraka** (Node.js) | Authenticated submission, DKIM signing, outbound queue/retries, TLS delivery. Plugin hooks emit every lifecycle event. |
| **Flask** (Python) | Web console + REST API + the internal event sink. New "mail console" UI. |
| **PostgreSQL** | Apps, messages, delivery events, domains, settings. |
| **Caddy** | Reverse proxy + automatic Let's Encrypt TLS for the dashboard. |

**Authenticated submission only — never an open relay.** Recipients are accepted
only after an app authenticates with valid per-app credentials.

## Install (Ubuntu)

```bash
git clone https://github.com/ruolez/ssmtp-server.git
cd ssmtp-server
sudo bash install.sh
```

The installer prompts for your domain, mail hostname, server IP, and an admin
login; opens the firewall; generates DKIM keys and secrets; and brings the stack
up. It then prints the DNS records to publish. Choose **staging** TLS while you
test DNS, then re-run and choose **production** for trusted certificates.

### Requirements

- A VPS with a **dedicated IP**, a **domain**, and **DNS control**.
- **Outbound port 25 open** and the IP not on blocklists (confirm with your provider).
- Ability to set **reverse DNS (PTR)** for the IP at the provider.

## Local development

```bash
cp .env.example .env
docker compose up -d --build
# Console (plain HTTP, no Caddy): http://localhost:8025  (admin / changeme)
```

Submission ports are published on 25 / 587 / 465. Send a test with any SMTP
client using credentials created on the **Applications** page.

## Using it from your apps

Create an application in the console to get a unique SMTP username/password,
then point your app's SMTP client at:

- Host: `mail.yourdomain.com`
- Port: `587` (STARTTLS) or `465` (implicit TLS)
- Auth: the app's username + password

Every message then appears in **Activity** with its delivery status and timeline.

## Deliverability checklist

1. Publish **A**, **SPF**, **DKIM**, **DMARC** (see the **DNS & DKIM** page) — [DNS_SETUP.md](DNS_SETUP.md).
2. Set **PTR / reverse DNS** at your VPS provider.
3. Switch TLS to **production** and verify each record from the dashboard.
4. Warm up gradually if volume grows.

See [DBSCHEMA.md](DBSCHEMA.md) for the data model.

## Updating

```bash
cd /opt/ssmtp-server && sudo bash install.sh   # choose Update
```

Update backs up the database, pulls the latest code, and rebuilds the app
containers. The Caddy certificate volume is **left untouched**, so TLS certs are
preserved and never needlessly re-issued (protects the Let's Encrypt rate limit).
