"""Seed a vulnerable or fixed demo database without resetting it accidentally."""
import argparse
import os
import sqlite3

from werkzeug.security import generate_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "chirp.db")
FIXED_DB_PATH = os.path.join(APP_DIR, "chirp_fixed.db")

USERS = [
    ("admin", "S3cr3t_@dm1n_2026", "admin@chirp.ctf", "I run this place."),
    ("alice", "password123", "alice@chirp.ctf", "coffee + code"),
    ("bob", "hunter2", "bob@chirp.ctf", "just here for the memes"),
]
TWEETS = [
    (1, "Welcome to Chirp! Beta is live."),
    (2, "first post, hi everyone"),
    (3, "who else is up at 3am"),
    (1, "Reminder: do NOT share your password."),
]
DMS = [
    ("alice", "bob", "hey, you free later?"),
    ("admin", "alice", "FLAG{idor_lets_you_read_my_dms}"),
    ("bob", "admin", "can you reset my password?"),
]


def seed_database(path, *, fixed=False, reset=False):
    if os.path.exists(path):
        if not reset:
            raise FileExistsError(f"{path} already exists. Use --reset for a fresh demo.")
        os.remove(path)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT,
                bio TEXT
            );
            CREATE TABLE tweets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE dms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                body TEXT NOT NULL
            );
        """)
        users = [
            (name, generate_password_hash(password) if fixed else password, email, bio)
            for name, password, email, bio in USERS
        ]
        db.executemany(
            "INSERT INTO users (username, password, email, bio) VALUES (?,?,?,?)", users
        )
        db.executemany("INSERT INTO tweets (user_id, body) VALUES (?,?)", TWEETS)
        db.executemany("INSERT INTO dms (sender, recipient, body) VALUES (?,?,?)", DMS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed", action="store_true", help="Seed chirp_fixed.db with hashed passwords")
    parser.add_argument("--reset", action="store_true", help="Replace only the selected demo database")
    args = parser.parse_args()
    path = FIXED_DB_PATH if args.fixed else DB_PATH
    try:
        seed_database(path, fixed=args.fixed, reset=args.reset)
    except FileExistsError as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Seeded {os.path.basename(path)} (users: admin / alice / bob)")
