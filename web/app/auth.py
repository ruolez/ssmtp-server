"""Session-based admin authentication for the web UI."""

from __future__ import annotations

import hmac
import os
from functools import wraps

from flask import jsonify, redirect, request, session, url_for


def login_required(view):
    """Gate HTML pages: redirect anonymous users to the login screen."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def api_login_required(view):
    """Gate JSON APIs: return 401 instead of redirecting."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"success": False, "error": "Authentication required"}), 401
        return view(*args, **kwargs)
    return wrapped


def internal_secret_required(view):
    """Gate the Haraka -> Flask event API with a shared secret header."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = os.environ.get("INTERNAL_SECRET", "")
        provided = request.headers.get("X-Internal-Secret", "")
        if not expected or not hmac.compare_digest(expected, provided):
            return jsonify({"success": False, "error": "Forbidden"}), 403
        return view(*args, **kwargs)
    return wrapped
