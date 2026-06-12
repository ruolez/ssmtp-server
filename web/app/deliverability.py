"""DKIM key management and DNS record generation / verification.

DKIM keys live in the shared `dkim_keys` volume at /dkim/<domain>/, in the
layout Haraka's bundled dkim_sign plugin expects:
    /dkim/<domain>/private    PEM private key
    /dkim/<domain>/selector   the selector (e.g. "default")
    /dkim/<domain>/public     PEM public key (reference)
The public key's base64 DER is what gets published as the DKIM DNS TXT record.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import dns.resolver
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DKIM_ROOT = Path("/dkim")
DEFAULT_SELECTOR = "default"


def _domain_dir(domain: str) -> Path:
    return DKIM_ROOT / domain


def dkim_key_exists(domain: str) -> bool:
    d = _domain_dir(domain)
    return (d / "private").exists() and (d / "selector").exists()


def ensure_dkim_key(domain: str, selector: str = DEFAULT_SELECTOR) -> str:
    """Generate a DKIM keypair for the domain if absent. Returns public-key base64."""
    d = _domain_dir(domain)
    if dkim_key_exists(domain):
        return public_key_b64(domain)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    d.mkdir(parents=True, exist_ok=True)
    (d / "private").write_bytes(private_pem)
    (d / "public").write_bytes(public_pem)
    (d / "selector").write_text(selector)
    os.chmod(d / "private", 0o600)
    return public_key_b64(domain)


def public_key_b64(domain: str) -> str:
    """Base64 DER of the public key (the value after p= in the DKIM TXT record)."""
    public_pem = (_domain_dir(domain) / "public").read_bytes()
    public_key = serialization.load_pem_public_key(public_pem)
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(der).decode()


def get_selector(domain: str) -> str:
    sel = _domain_dir(domain) / "selector"
    return sel.read_text().strip() if sel.exists() else DEFAULT_SELECTOR


def build_dns_records(domain: str, hostname: str, server_ip: str) -> list[dict]:
    """Return the DNS records the operator must publish for good deliverability."""
    selector = get_selector(domain)
    dkim_value = f"v=DKIM1; k=rsa; p={public_key_b64(domain)}"
    host_label = hostname[: -len("." + domain)] if hostname.endswith("." + domain) else hostname
    records = [
        {
            "type": "A",
            "host": host_label or "mail",
            "fqdn": hostname,
            "value": server_ip,
            "purpose": "Points the mail hostname at this server.",
            "required": True,
        },
        {
            "type": "PTR",
            "host": "(set at your VPS provider)",
            "fqdn": f"{server_ip} -> {hostname}",
            "value": hostname,
            "purpose": "Reverse DNS. Must resolve the IP back to the hostname. "
                       "Set this in your VPS provider's control panel, not in DNS.",
            "required": True,
        },
        {
            "type": "TXT",
            "host": "@",
            "fqdn": domain,
            "value": f"v=spf1 ip4:{server_ip} -all",
            "purpose": "SPF: authorises this IP to send for the domain.",
            "required": True,
        },
        {
            "type": "TXT",
            "host": f"{selector}._domainkey",
            "fqdn": f"{selector}._domainkey.{domain}",
            "value": dkim_value,
            "purpose": "DKIM public key: lets receivers verify the signature.",
            "required": True,
        },
        {
            "type": "TXT",
            "host": "_dmarc",
            "fqdn": f"_dmarc.{domain}",
            "value": f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}; aspf=s; adkim=s",
            "purpose": "DMARC policy. Start at p=none, tighten to quarantine/reject "
                       "once aligned.",
            "required": True,
        },
    ]
    return records


def _resolve_txt(name: str) -> list[str]:
    answers = dns.resolver.resolve(name, "TXT")
    return ["".join(p.decode() if isinstance(p, bytes) else p for p in r.strings)
            for r in answers]


def verify_record(record: dict) -> dict:
    """Live-resolve a single record and report pass/fail. PTR is informational."""
    result = {"status": "unknown", "found": None, "detail": ""}
    try:
        if record["type"] == "A":
            answers = dns.resolver.resolve(record["fqdn"], "A")
            found = [r.address for r in answers]
            result["found"] = ", ".join(found)
            result["status"] = "pass" if record["value"] in found else "fail"
        elif record["type"] == "PTR":
            # PTR is provider-side; we can only check forward resolution here.
            result["status"] = "info"
            result["detail"] = "Verify reverse DNS with your VPS provider."
        elif record["type"] == "TXT":
            txts = _resolve_txt(record["fqdn"])
            result["found"] = " | ".join(txts) if txts else None
            key = record["value"].split(";")[0].strip().lower()  # e.g. v=spf1 / v=dkim1
            match = any(key in t.lower() for t in txts) and (
                record["value"] in txts
                or any(_normalize(record["value"]) == _normalize(t) for t in txts)
                or key in ("v=spf1", "v=dmarc1") and any(t.lower().startswith(key) for t in txts)
            )
            result["status"] = "pass" if match else ("partial" if txts else "fail")
    except dns.resolver.NXDOMAIN:
        result["status"] = "fail"
        result["detail"] = "Name does not exist."
    except dns.resolver.NoAnswer:
        result["status"] = "fail"
        result["detail"] = "No record of this type."
    except Exception as e:  # noqa: BLE001 - surface any resolver error to the UI
        result["status"] = "error"
        result["detail"] = str(e)
    return result


def _normalize(value: str) -> str:
    return " ".join(value.split()).strip().lower()
