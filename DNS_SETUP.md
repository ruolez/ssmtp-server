# DNS & deliverability setup

Modern receivers (Gmail, Yahoo, Outlook) reject or spam-folder mail that lacks
SPF, DKIM, DMARC, and matching reverse DNS. Publish all of the records below for
your sending domain, then verify them on the dashboard's **DNS & DKIM** page.

Replace `example.com` / `mail.example.com` / `203.0.113.10` with your real
values. The exact records (including your generated DKIM key) are shown by the
installer and on the **DNS & DKIM** page.

## 1. A record — mail hostname

| Type | Host | Value |
|------|------|-------|
| A | `mail` | `203.0.113.10` |

## 2. PTR (reverse DNS) — set at your VPS provider

This is **not** a DNS-host record. Set it in your VPS provider's control panel so
the IP resolves back to the hostname:

```
203.0.113.10  ->  mail.example.com
```

Without a matching PTR, most providers mark your mail as spam.

## 3. SPF

| Type | Host | Value |
|------|------|-------|
| TXT | `@` | `v=spf1 ip4:203.0.113.10 -all` |

Authorises only this server's IP to send for the domain.

## 4. DKIM

| Type | Host | Value |
|------|------|-------|
| TXT | `default._domainkey` | `v=DKIM1; k=rsa; p=<your-public-key>` |

The selector is `default` and the public key is generated at install time
(private key stays on the server). Copy the exact value from the dashboard.

## 5. DMARC

| Type | Host | Value |
|------|------|-------|
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@example.com; aspf=s; adkim=s` |

Start with `p=none` and monitor the aggregate (`rua`) reports. Once SPF and DKIM
are consistently aligned, tighten to `p=quarantine` then `p=reject`.

## Verify

1. Open `https://mail.example.com/dns`.
2. Click **Verify now** — each record is live-resolved and marked pass / fail.
   (PTR is provider-side and shown as informational; confirm it separately, e.g.
   `dig -x 203.0.113.10`.)

## Go-live tips

- Test with **staging** TLS first so repeated installs don't burn the Let's
  Encrypt rate limit; switch to **production** once DNS verifies.
- Confirm **outbound port 25** is open and your IP is not blocklisted
  (check Spamhaus) before sending real mail.
- Send a first message to a Gmail/Outlook address and inspect the headers for
  `dkim=pass spf=pass dmarc=pass`.
- Ramp volume gradually on a fresh dedicated IP.
