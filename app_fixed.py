"""The repaired Chirp demo. Run alongside app.py to compare the same attacks."""
import argparse
from datetime import timedelta
import hmac
import os
import secrets
import sqlite3

from flask import (
    Flask, abort, g, redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "chirp_fixed.db")

app = Flask(__name__)
app.config.update(
    CHIRP_FIXED=True,
    # A random local key is renewed on restart; no key is committed to source.
    SECRET_KEY=os.environ.get("CHIRP_SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_NAME="chirp_fixed_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # The classroom demo runs on HTTP loopback. Enable Secure when using HTTPS.
    SESSION_COOKIE_SECURE=os.environ.get("CHIRP_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    MAX_CONTENT_LENGTH=64 * 1024,
    DEBUG=False,
)


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


def current_user():
    # V4 fix: Flask verifies the signed session before exposing these values.
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect_forms():
    if request.method == "POST":
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
            abort(400, description="This form has expired. Reload the page and try again.")


@app.after_request
def security_headers(response):
    # V2 defense in depth. Escaping stored content remains the primary fix.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; font-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/")
def index():
    db = get_db()
    tweets = db.execute(
        """SELECT tweets.id, tweets.body, tweets.created, users.username
           FROM tweets JOIN users ON tweets.user_id = users.id
           ORDER BY tweets.id DESC"""
    ).fetchall()
    members = db.execute("SELECT username FROM users ORDER BY username LIMIT 6").fetchall()
    return render_template("index.html", tweets=tweets, members=members, user=current_user())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None, user=current_user())
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    # V1 fix: bind the username as data; verify a salted password hash separately.
    row = get_db().execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    if row and check_password_hash(row["password"], password):
        session.clear()
        session["user_id"] = row["id"]
        session.permanent = True
        return redirect(url_for("index", notice="signed-in"))
    return render_template("login.html", error="Invalid credentials", user=current_user())


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index", notice="signed-out"))


@app.route("/tweet", methods=["POST"])
def tweet():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    body = request.form.get("body", "")
    if not body.strip():
        abort(400, description="Write something before posting.")
    db = get_db()
    cursor = db.execute("INSERT INTO tweets (user_id, body) VALUES (?, ?)", (user["id"], body))
    db.commit()
    return redirect(url_for("index", notice="posted", _anchor=f"post-{cursor.lastrowid}"))


@app.route("/user/<username>")
def profile(username):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        abort(404)
    tweets = db.execute(
        """SELECT tweets.id, tweets.body, tweets.created, users.username
           FROM tweets JOIN users ON tweets.user_id = users.id
           WHERE users.id = ? ORDER BY tweets.id DESC""", (row["id"],)
    ).fetchall()
    # V5 fix: pass the bio as data. Never compile it as a Jinja template.
    return render_template(
        "profile.html", profile_user=row, bio=row["bio"] or "",
        tweets=tweets, user=current_user(),
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if request.method == "POST":
        db = get_db()
        db.execute("UPDATE users SET bio = ? WHERE id = ?", (request.form.get("bio", ""), user["id"]))
        db.commit()
        return redirect(url_for("profile", username=user["username"], notice="saved"))
    return render_template("settings.html", user=user)


@app.route("/api/dm/<int:dm_id>")
def get_dm(dm_id):
    user = current_user()
    if not user:
        abort(401)
    # V3 fix: a signed-in user must also be a participant in this message.
    dm = get_db().execute(
        "SELECT * FROM dms WHERE id = ? AND (sender = ? OR recipient = ?)",
        (dm_id, user["username"], user["username"]),
    ).fetchone()
    if not dm:
        abort(404)
    return {"id": dm["id"], "from": dm["sender"], "to": dm["recipient"], "message": dm["body"]}


@app.route("/admin")
def admin():
    user = current_user()
    if not user or user["username"] != "admin":
        abort(403)
    users = get_db().execute("SELECT username, email FROM users").fetchall()
    return render_template("admin.html", users=users, user=user)


def error_page(error):
    if request.path.startswith("/api/"):
        return {"error": error.name, "status": error.code}, error.code
    return render_template(
        "error.html", status_code=error.code, error_title=error.name,
        error_description=error.description, user=current_user(),
    ), error.code


for status in (400, 401, 403, 404, 405, 413):
    app.register_error_handler(status, error_page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5051)
    args = parser.parse_args()
    if not os.path.exists(DB_PATH):
        parser.exit(1, "No fixed database found. Run: python3 seed.py --fixed\n")
    app.run(host="127.0.0.1", port=args.port, debug=False)
