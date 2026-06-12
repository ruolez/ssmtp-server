"""ssmtp-server web application: configuration + monitoring dashboard,
plus the internal event API that Haraka posts message lifecycle events to.
"""

from __future__ import annotations

import os
import secrets

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)

from app import deliverability
from app.auth import (api_login_required, internal_secret_required,
                      login_required)
from app.database import PostgresManager

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = PostgresManager()

MAIL_HOSTNAME = os.environ.get("MAIL_HOSTNAME", "mail.example.com")
MAIL_DOMAIN = os.environ.get("MAIL_DOMAIN", "example.com")
SERVER_IP = os.environ.get("SERVER_IP", "203.0.113.10")


def bootstrap() -> None:
    """Idempotent startup: schema, admin seed, default domain + DKIM key."""
    db.init_db()
    db.ensure_admin(
        os.environ.get("ADMIN_USERNAME", "admin"),
        os.environ.get("ADMIN_PASSWORD", "changeme"),
    )
    db.ensure_domain(MAIL_DOMAIN)
    try:
        public_b64 = deliverability.ensure_dkim_key(MAIL_DOMAIN)
        db.set_domain_dkim(MAIL_DOMAIN, deliverability.get_selector(MAIL_DOMAIN),
                           public_b64)
    except OSError as e:
        app.logger.warning("Could not initialise DKIM key for %s: %s", MAIL_DOMAIN, e)


with app.app_context():
    bootstrap()


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ----- health (unauthenticated) -------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ----- auth ----------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.form
        if db.verify_admin(data.get("username", ""), data.get("password", "")):
            session["admin"] = data.get("username")
            nxt = request.args.get("next") or url_for("dashboard")
            return redirect(nxt)
        return render_template("login.html", error="Invalid credentials"), 401
    if session.get("admin"):
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----- pages ---------------------------------------------------------------
def _ctx(active: str) -> dict:
    return {"active": active, "mail_hostname": MAIL_HOSTNAME,
            "mail_domain": MAIL_DOMAIN, "admin": session.get("admin")}


@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", **_ctx("dashboard"))


@app.route("/messages/<int:message_id>")
@login_required
def message_detail(message_id: int):
    return render_template("message.html", message_id=message_id, **_ctx("dashboard"))


@app.route("/apps")
@login_required
def apps_page():
    return render_template("apps.html", **_ctx("apps"))


@app.route("/settings")
@login_required
def settings_page():
    return render_template("settings.html", **_ctx("settings"))


@app.route("/dns")
@login_required
def dns_page():
    return render_template("dns.html", **_ctx("dns"))


# ----- API: stats + messages ----------------------------------------------
@app.route("/api/stats")
@api_login_required
def api_stats():
    return jsonify({"success": True, "data": db.dashboard_stats()})


@app.route("/api/messages")
@api_login_required
def api_messages():
    status = request.args.get("status")
    search = request.args.get("q")
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))
    rows = db.list_messages(status=status, search=search, limit=limit, offset=offset)
    return jsonify({"success": True, "data": rows})


@app.route("/api/messages/<int:message_id>")
@api_login_required
def api_message(message_id: int):
    msg = db.get_message(message_id)
    if not msg:
        return jsonify({"success": False, "error": "Not found"}), 404
    return jsonify({"success": True, "data": msg})


# ----- API: apps -----------------------------------------------------------
@app.route("/api/apps", methods=["GET"])
@api_login_required
def api_list_apps():
    return jsonify({"success": True, "data": db.list_apps()})


@app.route("/api/apps", methods=["POST"])
@api_login_required
def api_create_app():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    smtp_username = (data.get("smtp_username") or "").strip()
    if not name or not smtp_username:
        return jsonify({"success": False, "error": "name and smtp_username are required"}), 400
    password = data.get("password") or secrets.token_urlsafe(18)
    try:
        created = db.create_app(name, smtp_username, password,
                                int(data.get("rate_limit_per_hour", 0)))
    except Exception as e:  # noqa: BLE001 - likely a unique-constraint clash
        return jsonify({"success": False, "error": f"Could not create app: {e}"}), 400
    # Return the plaintext password ONCE so the operator can copy it.
    created["password"] = password
    return jsonify({"success": True, "data": created, "message": "App created"}), 201


@app.route("/api/apps/<int:app_id>", methods=["PATCH"])
@api_login_required
def api_update_app(app_id: int):
    data = request.get_json(silent=True) or {}
    new_password = data.get("password")
    db.update_app(
        app_id,
        enabled=data.get("enabled"),
        rate_limit_per_hour=data.get("rate_limit_per_hour"),
        password=new_password,
    )
    resp = {"success": True, "message": "App updated"}
    if new_password:
        resp["message"] = "Password reset"
    return jsonify(resp)


@app.route("/api/apps/<int:app_id>", methods=["DELETE"])
@api_login_required
def api_delete_app(app_id: int):
    db.delete_app(app_id)
    return jsonify({"success": True, "message": "App deleted"})


# ----- API: DNS / DKIM -----------------------------------------------------
@app.route("/api/dns")
@api_login_required
def api_dns():
    domain = request.args.get("domain", MAIL_DOMAIN)
    if not deliverability.dkim_key_exists(domain):
        deliverability.ensure_dkim_key(domain)
        db.set_domain_dkim(domain, deliverability.get_selector(domain),
                           deliverability.public_key_b64(domain))
    records = deliverability.build_dns_records(domain, MAIL_HOSTNAME, SERVER_IP)
    return jsonify({"success": True, "data": {"domain": domain, "records": records}})


@app.route("/api/dns/verify", methods=["POST"])
@api_login_required
def api_dns_verify():
    domain = (request.get_json(silent=True) or {}).get("domain", MAIL_DOMAIN)
    records = deliverability.build_dns_records(domain, MAIL_HOSTNAME, SERVER_IP)
    results = [{**rec, "check": deliverability.verify_record(rec)} for rec in records]
    if all(r["check"]["status"] in ("pass", "info") for r in results):
        db.mark_domain_verified(domain)
    return jsonify({"success": True, "data": {"domain": domain, "records": results}})


# ----- API: settings -------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
@api_login_required
def api_get_settings():
    return jsonify({"success": True, "data": {
        "mail_hostname": MAIL_HOSTNAME,
        "mail_domain": MAIL_DOMAIN,
        "server_ip": SERVER_IP,
        "max_retries": db.get_setting("max_retries", "5"),
        "default_rate_limit": db.get_setting("default_rate_limit", "0"),
        "domains": db.list_domains(),
    }})


@app.route("/api/settings", methods=["POST"])
@api_login_required
def api_set_settings():
    data = request.get_json(silent=True) or {}
    for key in ("max_retries", "default_rate_limit"):
        if key in data:
            db.set_setting(key, str(data[key]))
    return jsonify({"success": True, "message": "Settings saved"})


# ----- internal event API (Haraka -> Flask) -------------------------------
@app.route("/internal/events", methods=["POST"])
@internal_secret_required
def internal_events():
    e = request.get_json(silent=True) or {}
    event_type = e.get("type")
    queue_id = e.get("uuid")
    if not queue_id or not event_type:
        return jsonify({"success": False, "error": "type and uuid required"}), 400

    if event_type == "queued":
        db.upsert_message(
            queue_id,
            app_id=e.get("app_id"),
            message_id=e.get("message_id"),
            from_addr=e.get("mail_from"),
            to_addr=e.get("rcpt_to"),
            subject=e.get("subject"),
            size_bytes=e.get("size"),
            status="queued",
        )
    elif event_type in ("delivered", "bounce", "deferred"):
        status = {"delivered": "sent", "bounce": "bounced",
                  "deferred": "deferred"}[event_type]
        db.set_message_status(queue_id, status)
        db.add_delivery_event(
            queue_id, event_type,
            remote_mx=e.get("remote_mx"),
            smtp_code=str(e.get("smtp_code")) if e.get("smtp_code") is not None else None,
            smtp_response=e.get("smtp_response"),
            attempt_no=e.get("attempt_no"),
        )
    else:
        return jsonify({"success": False, "error": f"unknown type {event_type}"}), 400

    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
