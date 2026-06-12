# Database schema (PostgreSQL)

All tables are created automatically on first start by `web/app/database.py`
(`init_db()`). Timestamps are `TIMESTAMPTZ`; the UI renders them in
America/Chicago.

## `admin_users`
Web console logins. Seeded with the admin from `.env` if empty.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| username | text unique | |
| password_hash | text | bcrypt |

## `apps`
One row per application allowed to relay. SMTP auth is checked against this
table by Haraka's `auth_apps` plugin.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | referenced by `messages.app_id` |
| name | text unique | friendly label shown in Activity |
| smtp_username | text unique | what the app authenticates as |
| smtp_password_hash | text | bcrypt (shared format with Haraka `bcryptjs`) |
| api_key | text unique | reference key (`sk_…`) |
| enabled | boolean | disabled apps cannot authenticate |
| rate_limit_per_hour | integer | 0 = unlimited |
| created_at | timestamptz | |

## `messages`
One row per accepted submission, keyed by Haraka's transaction UUID.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| app_id | int FK → apps | nullable (app may be deleted) |
| queue_id | text unique | Haraka transaction UUID (correlates events) |
| message_id | text | RFC Message-ID header |
| from_addr / to_addr | text | envelope sender / recipients |
| subject | text | |
| size_bytes | int | |
| status | text | `received` → `queued` → `sent` / `deferred` / `bounced` |
| received_at / updated_at | timestamptz | |

## `delivery_events`
Append-only delivery timeline; powers the per-message lifecycle view.

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| message_id | int FK → messages | cascade delete |
| event_type | text | `delivered` / `deferred` / `bounce` |
| remote_mx | text | destination MX |
| smtp_code | text | remote SMTP code |
| smtp_response | text | remote SMTP response text |
| attempt_no | int | delivery attempt number |
| occurred_at | timestamptz | |

## `domains`
Sending domains and their DKIM public material (private keys live on disk in the
`dkim_keys` volume, never in the DB).

| Column | Type | Notes |
|--------|------|-------|
| id | serial PK | |
| domain | text unique | |
| dkim_selector | text | e.g. `default` |
| dkim_public_key | text | base64 DER (the `p=` value) |
| dns_verified_at | timestamptz | set when all records verify |

## `settings`
Simple key/value store (`max_retries`, `default_rate_limit`, …).
