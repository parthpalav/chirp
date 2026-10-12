"""
Chirp — a deliberately vulnerable Twitter-like app for CTF / training use.

!!! WARNING !!!
This application contains INTENTIONAL security vulnerabilities. It is for
isolated, offline CTF and educational use only. Never deploy it on a public
network or with real user data.

Five planted vulnerabilities (see docs/VULNERABILITIES.md):
  V1  SQL Injection            -> login form
  V2  Stored XSS               -> tweet body rendering
  V3  IDOR                     -> /api/dm/<id>
  V4  Broken auth (alg=none)   -> session token verification
  V5  Server-Side Template Inj -> profile bio rendering
"""

import base64
import hashlib
import hmac
import json
import os
import sqlite3

from flask import (
    Flask,
    g,
    redirect,
    render_template,
    render_template_string,
    request,
    make_response,
    abort,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "chirp.db")
SECRET = b"ctf-super-secret-signing-key"  # used by the (broken) token code

app = Flask(__name__)


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --------------------------------------------------------------------------
# Auth tokens  (V4 lives here)
# --------------------------------------------------------------------------
def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(username: str) -> str:
    header = {"alg": "HS256", "typ": "CHIRP"}
    payload = {"user": username}
    h = b64url(json.dumps(header).encode())
    p = b64url(json.dumps(payload).encode())
    sig = hmac.new(SECRET, f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{b64url(sig)}"


def verify_token(token: str):
    """
    V4 — BROKEN AUTH: trusts the 'alg' field from the token itself.
    A token with {"alg":"none"} skips signature verification entirely,
    so an attacker can forge any identity (e.g. the 'admin' user).
    """
    try:
        h_b64, p_b64, sig_b64 = token.split(".")
        header = json.loads(b64url_decode(h_b64))
        payload = json.loads(b64url_decode(p_b64))

        if header.get("alg") == "none":
            return payload.get("user")  # <-- no signature check

        expected = hmac.new(
            SECRET, f"{h_b64}.{p_b64}".encode(), hashlib.sha256
        ).digest()
        if hmac.compare_digest(expected, b64url_decode(sig_b64)):
            return payload.get("user")
    except Exception:
        return None
    return None


def current_user():
    token = request.cookies.get("session")
    if not token:
        return None
    username = verify_token(token)
    if not username:
        return None
    db = get_db()
    return db.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    tweets = db.execute(
        """SELECT tweets.id, tweets.body, tweets.created, users.username
           FROM tweets JOIN users ON tweets.user_id = users.id
           ORDER BY tweets.id DESC"""
    ).fetchall()
    members = db.execute(
        "SELECT username FROM users ORDER BY username LIMIT 6"
    ).fetchall()
    return render_template(
        "index.html", tweets=tweets, members=members, user=current_user()
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    db = get_db()

    # V1 — SQL INJECTION: user input concatenated straight into the query.
    # Try username:  admin' --
    query = (
        "SELECT * FROM users WHERE username = '%s' AND password = '%s'"
        % (username, password)
    )
    try:
        row = db.execute(query).fetchone()
    except sqlite3.Error:
        row = None

    if row:
        resp = make_response(redirect("/"))
        resp.set_cookie("session", make_token(row["username"]))
        return resp
    return render_template("login.html", error="Invalid credentials")


@app.route("/logout")
def logout():
    resp = make_response(redirect("/"))
    resp.delete_cookie("session")
    return resp


@app.route("/tweet", methods=["POST"])
def tweet():
    user = current_user()
    if not user:
        return redirect("/login")
    body = request.form.get("body", "")
    db = get_db()
    # Body is parameterized here (no SQLi) but is rendered unsafely later (V2).
    db.execute(
        "INSERT INTO tweets (user_id, body) VALUES (?, ?)", (user["id"], body)
    )
    db.commit()
    return redirect("/")


@app.route("/user/<username>")
def profile(username):
    db = get_db()
    row = db.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    if not row:
        abort(404)

    # V5 — SERVER-SIDE TEMPLATE INJECTION: the bio is concatenated into a
    # template string and rendered, so Jinja expressions in a bio execute.
    # Try a bio of:  {{ 7*7 }}  or  {{ config }}
    bio_html = render_template_string(
        "<div class='bio'>" + (row["bio"] or "") + "</div>"
    )
    tweets = db.execute(
        """SELECT tweets.id, tweets.body, tweets.created, users.username
           FROM tweets JOIN users ON tweets.user_id = users.id
           WHERE users.id = ? ORDER BY tweets.id DESC""",
        (row["id"],),
    ).fetchall()
    return render_template(
        "profile.html",
        profile_user=row,
        bio_html=bio_html,
        tweets=tweets,
        user=current_user(),
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    user = current_user()
    if not user:
        return redirect("/login")
    db = get_db()
    if request.method == "POST":
        bio = request.form.get("bio", "")
        db.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, user["id"]))
        db.commit()
        return redirect("/user/" + user["username"])
    return render_template("settings.html", user=user)


@app.route("/api/dm/<int:dm_id>")
def get_dm(dm_id):
    user = current_user()
    if not user:
        abort(401)
    db = get_db()
    # V3 — IDOR: fetches a DM by id with no check that it belongs to the
    # requesting user. Any logged-in user can read anyone's DMs by id.
    dm = db.execute(
        "SELECT * FROM dms WHERE id = ?", (dm_id,)
    ).fetchone()
    if not dm:
        abort(404)
    return {
        "id": dm["id"],
        "from": dm["sender"],
        "to": dm["recipient"],
        "message": dm["body"],
    }


@app.route("/admin")
def admin():
    user = current_user()
    if not user or user["username"] != "admin":
        abort(403)
    db = get_db()
    users = db.execute("SELECT username, email FROM users").fetchall()
    return render_template("admin.html", users=users, user=user)


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("No database found. Run:  python seed.py")
    app.run(host="127.0.0.1", port=5000, debug=True)
