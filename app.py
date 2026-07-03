"""
AKF website backend.

The frontend (index.html, register.html, dashboard.html, etc.) was already
written to call routes like /login, /register, /api/announcements,
/api/fund, /api/members and so on -- but no server existed to answer those
calls, which is why login/registration/the member dashboard/the donate
counter/the contact form all appeared "broken". This file provides that
server.

Data is stored in small JSON files under data/ so nothing extra needs to be
installed or configured to try it out. Swap load_json/save_json for a real
database before putting this in production.
"""

import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
ANNOUNCEMENTS_FILE = DATA_DIR / "announcements.json"
FUND_FILE = DATA_DIR / "fund.json"
CONTACTS_FILE = DATA_DIR / "contacts.json"

OTP_TTL_SECONDS = 10 * 60
PASSWORD_RULES = [
    (r".{8,}", "Password must be at least 8 characters."),
    (r"[A-Z]", "Password must include an uppercase letter."),
    (r"[a-z]", "Password must include a lowercase letter."),
    (r"[0-9]", "Password must include a number."),
    (r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]", "Password must include a special character."),
]

app = Flask(
    __name__,
    static_folder=str(BASE_DIR),
    static_url_path="",
    template_folder=str(BASE_DIR / "templates"),
)
app.secret_key = "akf-dev-secret-change-me-before-deploying"  # TODO: set via env var in production
app.logger.setLevel(logging.INFO)


# ─────────────────────────────── storage helpers ────────────────────────────
def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_users() -> dict:
    return load_json(USERS_FILE, {})


def save_users(users: dict):
    save_json(USERS_FILE, users)


def load_announcements() -> list:
    return load_json(ANNOUNCEMENTS_FILE, [])


def save_announcements(items: list):
    save_json(ANNOUNCEMENTS_FILE, items)


def load_fund() -> dict:
    return load_json(FUND_FILE, {"amount": 0, "updated_by": "AKF Board", "updated_at": "—"})


def save_fund(fund: dict):
    save_json(FUND_FILE, fund)


def load_contacts() -> list:
    return load_json(CONTACTS_FILE, [])


def save_contacts(items: list):
    save_json(CONTACTS_FILE, items)


def mask_email(email: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked = local[0] + "*" * max(len(local) - 1, 1)
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


def display_role(role_level: str) -> str:
    return "Board Member" if role_level == "board" else "Member"


def require_board():
    """Returns (user_dict, username) if the logged-in user is a board member, else None."""
    username = session.get("user")
    if not username:
        return None
    users = load_users()
    user = users.get(username)
    if not user or user.get("role_level") != "board":
        return None
    return user, username


# ───────────────────────────────── static pages ─────────────────────────────
@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/about")
def about_pretty():
    return send_from_directory(BASE_DIR, "about.html")


@app.route("/programs")
def programs_pretty():
    return send_from_directory(BASE_DIR, "programs.html")


@app.route("/contact")
def contact_pretty():
    return send_from_directory(BASE_DIR, "contact.html")


@app.route("/donate")
def donate_pretty():
    return send_from_directory(BASE_DIR, "donate.html")


@app.route("/ngh")
def ngh_pretty():
    return send_from_directory(BASE_DIR, "ngh.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return send_from_directory(BASE_DIR, "dashboard.html")


# ────────────────────────────────── auth: register ───────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    role_choice = request.form.get("role", "common")

    error = None
    if not all([name, username, email, password, confirm_password]):
        error = "Please fill in all fields."
    elif "@" not in email or "." not in email.split("@")[-1]:
        error = "Please enter a valid email address."
    elif password != confirm_password:
        error = "Passwords do not match."
    else:
        for pattern, message in PASSWORD_RULES:
            if not re.search(pattern, password):
                error = message
                break

    if not error:
        users = load_users()
        if username in users:
            error = "That username is already taken."
        elif any(u["email"] == email for u in users.values()):
            error = "An account with that email already exists."

    if error:
        return render_template("register.html", error=error)

    otp = f"{random.randint(0, 999999):06d}"
    session["pending_reg"] = {
        "name": name,
        "username": username,
        "email": email,
        "password_hash": generate_password_hash(password),
        "role_level": "board" if role_choice == "admin" else "member",
        "otp": otp,
        "otp_expires": time.time() + OTP_TTL_SECONDS,
    }
    # No email service is configured, so the OTP is logged server-side instead
    # of actually being emailed. Wire up a real mail provider before deploying.
    app.logger.info("[DEV ONLY] OTP for %s is %s", email, otp)
    return redirect(url_for("register_verify"))


@app.route("/register/verify", methods=["GET", "POST"])
def register_verify():
    pending = session.get("pending_reg")
    if not pending:
        return redirect(url_for("register"))

    masked_email = mask_email(pending["email"])

    if request.method == "GET":
        return render_template("otp_verify.html", masked_email=masked_email)

    submitted_otp = request.form.get("otp", "").strip()

    if time.time() > pending["otp_expires"]:
        return render_template(
            "otp_verify.html", masked_email=masked_email,
            error="That OTP has expired. Please request a new one.",
        )

    if submitted_otp != pending["otp"]:
        return render_template(
            "otp_verify.html", masked_email=masked_email,
            error="Incorrect OTP. Please try again.",
        )

    users = load_users()
    users[pending["username"]] = {
        "name": pending["name"],
        "username": pending["username"],
        "email": pending["email"],
        "password_hash": pending["password_hash"],
        "role_level": pending["role_level"],
    }
    save_users(users)
    session.pop("pending_reg", None)
    return redirect(url_for("login", registered="1"))


@app.route("/register/resend_otp")
def resend_otp():
    pending = session.get("pending_reg")
    if pending:
        pending["otp"] = f"{random.randint(0, 999999):06d}"
        pending["otp_expires"] = time.time() + OTP_TTL_SECONDS
        session["pending_reg"] = pending
        app.logger.info("[DEV ONLY] Resent OTP for %s is %s", pending["email"], pending["otp"])
    return redirect(url_for("register_verify"))


# ────────────────────────────────── auth: login ──────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login_form.html", registered=request.args.get("registered"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    users = load_users()
    user = users.get(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login_form.html", error="Invalid username or password.")

    session["user"] = username
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))


# ────────────────────────────────────── API ──────────────────────────────────
@app.route("/api/me")
def api_me():
    username = session.get("user")
    if not username:
        return jsonify(error="unauthorized"), 401
    users = load_users()
    user = users.get(username)
    if not user:
        session.pop("user", None)
        return jsonify(error="unauthorized"), 401
    return jsonify(
        name=user["name"],
        username=username,
        email=user["email"],
        role=display_role(user["role_level"]),
        role_level=user["role_level"],
    )


@app.route("/api/announcements")
def api_announcements():
    return jsonify(load_announcements())


@app.route("/api/announcement", methods=["POST"])
def api_post_announcement():
    auth = require_board()
    if not auth:
        return jsonify(success=False, error="Unauthorized"), 403
    user, _ = auth

    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if not title or not content:
        return jsonify(success=False, error="Title and content are required."), 400

    announcements = load_announcements()
    new_id = max((a["id"] for a in announcements), default=0) + 1
    announcements.insert(0, {
        "id": new_id,
        "title": title,
        "content": content,
        "posted_by": user["name"],
        "posted_at": datetime.now().strftime("%d %b %Y, %I:%M %p"),
    })
    save_announcements(announcements)
    return jsonify(success=True)


@app.route("/api/announcement/<int:ann_id>", methods=["DELETE"])
def api_delete_announcement(ann_id):
    auth = require_board()
    if not auth:
        return jsonify(success=False, error="Unauthorized"), 403
    announcements = [a for a in load_announcements() if a["id"] != ann_id]
    save_announcements(announcements)
    return jsonify(success=True)


@app.route("/api/fund", methods=["GET", "POST"])
def api_fund():
    if request.method == "GET":
        return jsonify(load_fund())

    auth = require_board()
    if not auth:
        return jsonify(success=False, error="Unauthorized"), 403
    user, _ = auth

    data = request.get_json(force=True, silent=True) or {}
    try:
        amount = int(data.get("amount"))
        if amount < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(success=False, error="Enter a valid, non-negative amount."), 400

    save_fund({
        "amount": amount,
        "updated_by": user["name"],
        "updated_at": datetime.now().strftime("%d %b %Y, %I:%M %p"),
    })
    return jsonify(success=True)


@app.route("/api/members")
def api_members():
    auth = require_board()
    if not auth:
        return jsonify([]), 403
    users = load_users()
    return jsonify([
        {
            "name": u["name"],
            "email": u["email"],
            "role": display_role(u["role_level"]),
            "role_level": u["role_level"],
        }
        for u in users.values()
    ])


@app.route("/api/contact", methods=["POST"])
def api_contact():
    data = request.get_json(force=True, silent=True) or {}
    entry = {
        "name": (data.get("name") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "subject": (data.get("subject") or "").strip(),
        "message": (data.get("message") or "").strip(),
        "received_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not entry["name"] or not entry["email"] or not entry["message"]:
        return jsonify(success=False, error="Name, email, and message are required."), 400

    contacts = load_contacts()
    contacts.append(entry)
    save_contacts(contacts)
    # No email service configured -- messages just land in data/contacts.json
    # for now. Wire up a real notification (email/Slack) before deploying.
    app.logger.info("[Contact] %s <%s>: %s", entry["name"], entry["email"], entry["subject"])
    return jsonify(success=True)


if __name__ == "__main__":
    app.run(debug=False, port=5000)
