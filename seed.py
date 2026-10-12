"""Create and seed the Chirp database with demo users, tweets, and DMs."""
import os
import sqlite3

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "chirp.db")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

db = sqlite3.connect(DB_PATH)
db.executescript(
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,      -- stored in plaintext (part of the lesson)
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
    """
)

users = [
    ("admin", "S3cr3t_@dm1n_2026", "admin@chirp.ctf", "I run this place."),
    ("alice", "password123", "alice@chirp.ctf", "coffee + code"),
    ("bob", "hunter2", "bob@chirp.ctf", "just here for the memes"),
]
db.executemany(
    "INSERT INTO users (username, password, email, bio) VALUES (?,?,?,?)", users
)

tweets = [
    (1, "Welcome to Chirp! Beta is live."),
    (2, "first post, hi everyone"),
    (3, "who else is up at 3am"),
    (1, "Reminder: do NOT share your password."),
]
db.executemany("INSERT INTO tweets (user_id, body) VALUES (?,?)", tweets)

dms = [
    ("alice", "bob", "hey, you free later?"),
    ("admin", "alice", "FLAG{idor_lets_you_read_my_dms}"),
    ("bob", "admin", "can you reset my password?"),
]
db.executemany(
    "INSERT INTO dms (sender, recipient, body) VALUES (?,?,?)", dms
)

db.commit()
db.close()
print("Seeded chirp.db  (users: admin / alice / bob)")
