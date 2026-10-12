# Chirp — GUI Walkthrough: Exploit and Fix (browser only, no curl)

All five vulnerabilities can be exploited in a browser with no command line:
**V1, V2 and V5** are pure point-and-click, **V3** uses the address bar (there is
no DM page in the UI), and **V4** uses the browser's Developer Tools to set a
cookie. **Part 2** then applies the fix and re-checks each one in the browser.

Every step below was executed in a real browser against the running app.

> ⚠️ Localhost, offline, training only. The vulnerable app's header shows
> **"Training edition"**; the hardened app shows **"Fixed edition"** — use that
> to be sure which one you are looking at.

**Prerequisites:** finish Part 1–7 of [RUNBOOK.md](RUNBOOK.md) first — clone,
virtualenv, install, seed, and `python app.py` running at
**http://127.0.0.1:5000**.

---

## Where each vulnerability lives

| # | Vulnerability | Vulnerable file | UI entry point |
|---|---------------|-----------------|----------------|
| V1 | SQL Injection (auth bypass) | `app.py` `login()` | `/login` form |
| V2 | Stored XSS | `templates/components.html` | home-feed composer |
| V3 | IDOR | `app.py` `get_dm()` | address bar → `/api/dm/<id>` |
| V4 | Broken auth (`alg=none`) | `app.py` `verify_token()` | DevTools → cookie `session` |
| V5 | SSTI (→ RCE) | `app.py` `profile()` | Settings → Bio, then profile |

---

# Part 1 — Exploitation (browser)

## V1 — SQL Injection: sign in as admin without the password

**The vulnerable code** (`app.py`, `login()`): user input is concatenated into
the SQL string, so the `--` comment can drop the password check.

```python
query = (
    "SELECT * FROM users WHERE username = '%s' AND password = '%s'"
    % (username, password)
)
row = db.execute(query).fetchone()
```

**Steps:**

1. Go to **http://127.0.0.1:5000/login**.
2. In the **Username** field type (including the space, then two dashes):

   ```
   admin' --
   ```

   This makes the query `... WHERE username = 'admin' --' AND password = 'x'`;
   `--` comments out the rest.
3. In the **Password** field type anything, e.g. `x`.
4. Click **Sign in**.

**Result:** you land on the feed signed in as **@admin** (top-right shows
`@admin`, and an **Admin** item appears in the left navigation). The password
was never checked. Click **Admin** in the left nav to confirm elevated access.

---

## V2 — Stored XSS: a script that runs for everyone

**The vulnerable code** (`templates/components.html`, post macro): `| safe`
disables Jinja's auto-escaping, so stored markup executes.

```jinja
<div class="post-body">{{ tweet['body'] | safe }}</div>
```

**Steps:**

1. Sign in (use V1, or a real account).
2. Go to the home feed **http://127.0.0.1:5000/**.
3. In the composer box labeled **“What’s on your mind?”** type:

   ```html
   <script>alert(document.cookie)</script>
   ```

   (A non-blocking payload for demos: `<img src=x onerror="alert(document.cookie)">`.)
4. Click **Post** (or press **Ctrl / Cmd + Enter**).

**Result:** the post is saved and the alert fires immediately — and it fires for
*every* visitor who loads the feed, because the body is rendered unescaped.

---

## V3 — IDOR: read other people’s private messages

**The vulnerable code** (`app.py`, `get_dm()`): the row is fetched by id with no
check that the caller is a participant.

```python
dm = db.execute("SELECT * FROM dms WHERE id = ?", (dm_id,)).fetchone()
```

**Steps:**

1. Sign in as any user (V1 works).
2. Click the address bar and enter:

   ```
   http://127.0.0.1:5000/api/dm/2
   ```

3. Press **Enter**.

**Result:** the browser shows the JSON, including a flag belonging to other
users:

```json
{ "from": "admin", "id": 2, "message": "FLAG{idor_lets_you_read_my_dms}", "to": "alice" }
```

Change the number (`1`, `2`, `3`, …) to walk through every message.

---

## V4 — `alg=none` forgery: become admin via a cookie

**The vulnerable code** (`app.py`, `verify_token()`): the server trusts the
token's own `alg` header, so `{"alg":"none"}` skips signature verification.

```python
if header.get("alg") == "none":
    return payload.get("user")      # <-- no signature check
```

**Steps:**

1. Click **Sign out** (top-right) so the forgery is genuine.
2. Open DevTools: **F12**, or **Ctrl+Shift+I** (Windows/Linux) /
   **Cmd+Option+I** (macOS).
3. **Easiest way — Console tab.** Paste this and press Enter:

   ```javascript
   document.cookie = "session=eyJhbGciOiJub25lIiwidHlwIjoiQ0hJUlAifQ.eyJ1c2VyIjoiYWRtaW4ifQ.; path=/";
   ```

   That value is the forged token: base64url `{"alg":"none","typ":"CHIRP"}` +
   `.` + base64url `{"user":"admin"}` + `.` (a trailing dot = empty signature).

   **Or, without the Console:** DevTools → **Application** tab → **Storage →
   Cookies → http://127.0.0.1:5000** → add a cookie named **`session`** with the
   value above.
4. Type **http://127.0.0.1:5000/admin** in the address bar and press Enter.

**Result:** you are treated as `admin` and the page exposes
`FLAG{alg_none_made_you_admin}` in the lower-right “Session note”.

*(Works because the server trusts the token's `alg` and the vulnerable app's
cookie is not `HttpOnly`, so it can be set from the Console. A generated token —
not hand-typed — is in [VULNERABILITIES.md](VULNERABILITIES.md).)*

---

## V5 — SSTI: run server-side template code from your bio

**The vulnerable code** (`app.py`, `profile()`): the user-controlled bio is
compiled as a Jinja template.

```python
bio_html = render_template_string(
    "<div class='bio'>" + (row["bio"] or "") + "</div>"
)
```

**Steps:**

1. Sign in.
2. Click **Settings** in the left navigation (or open
   **http://127.0.0.1:5000/settings**).
3. In the **Bio** textarea, replace the text with:

   ```jinja
   {{7*7}}
   ```

4. Click **Save changes**.

**Result:** you are redirected to your profile and the bio shows **`49`** — the
expression was executed server-side.

Set the bio to these and re-open your profile to prove escalation to remote code
execution:

```jinja
{{ config.items() }}
{{ ''.__class__.__mro__[1].__subclasses__() }}
```

---

# Part 2 — Fixing, and checking on the fixed build

Fixing is **not** something you do in the GUI — it is a code change. You apply it
once, then reopen the app in the browser and confirm each attack now fails.

## 2.0 — Start the hardened build

```bash
python seed.py --fixed      # hashed passwords → chirp_fixed.db (once)
python app_fixed.py         # http://127.0.0.1:5051  (header: "Fixed edition")
# optional: a different port
python app_fixed.py --port 5060
```

Keep the vulnerable `:5000` running side by side to compare. `app_fixed.py` is
the reference implementation of every fix below; the same changes applied by hand
to `app.py` behave identically.

> On the fixed build the login, post, settings and sign-out forms carry a hidden
> CSRF token that renders automatically — you still just click the buttons
> normally. A raw POST without it is rejected with `400`.

---

## Fix V1 — SQL Injection

**Before** (`app.py` `login()`): string-built SQL + plaintext compare.

```python
query = (
    "SELECT * FROM users WHERE username = '%s' AND password = '%s'"
    % (username, password)
)
row = db.execute(query).fetchone()
```

**After** — bind the username as data; verify a password hash separately:

```python
from werkzeug.security import check_password_hash
row = db.execute(
    "SELECT * FROM users WHERE username = ?", (username,)
).fetchone()
if row and check_password_hash(row["password"], password):
    session.clear()
    session["user_id"] = row["id"]
    session.permanent = True
    return redirect(url_for("index", notice="signed-in"))
return render_template("login.html", error="Invalid credentials", user=current_user())
```

*(Hashing needs `python seed.py --fixed`; the plaintext `chirp.db` still works if
you only parameterize, but hashing is the real fix.)*

**Check on the fixed build (browser):**

1. Go to **http://127.0.0.1:5051/login**.
2. **Username** = `admin' --`, **Password** = `x`, click **Sign in**.
3. **Expected:** an error banner — **“Couldn’t sign you in. Invalid
   credentials.”** — and you stay signed out (no `@admin`, no Admin nav item).
4. Sign in with the real credentials (`admin` / `S3cr3t_@dm1n_2026`) to confirm
   legitimate login still works.

---

## Fix V2 — Stored XSS

**Before** (`templates/components.html`): escaping disabled with `| safe`.

```jinja
<div class="post-body">{{ tweet['body'] | safe }}</div>
```

**After** — let Jinja auto-escape (`< > & " '`):

```jinja
<div class="post-body">{{ tweet['body'] }}</div>
```

Defense in depth (already in `app_fixed.py`): send a CSP header.

```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
```

**Check on the fixed build (browser):**

1. Sign in (e.g. `alice` / `password123`).
2. Post `<script>alert(document.cookie)</script>` via the composer and click
   **Post**.
3. **Expected:** the text appears **literally** in the feed (no alert fires). View
   source shows it escaped as `&lt;script&gt;…&lt;/script&gt;`.

---

## Fix V3 — IDOR

**Before** (`app.py` `get_dm()`): fetched by id, no ownership check.

```python
dm = db.execute("SELECT * FROM dms WHERE id = ?", (dm_id,)).fetchone()
```

**After** — scope the query to the caller and hide existence with `404`:

```python
dm = db.execute(
    "SELECT * FROM dms WHERE id = ? AND (sender = ? OR recipient = ?)",
    (dm_id, user["username"], user["username"]),
).fetchone()
if not dm:
    abort(404)
```

**Check on the fixed build (browser):**

1. Sign in as **alice**.
2. Enter **http://127.0.0.1:5051/api/dm/3** in the address bar (a DM between bob
   and admin — alice is not a participant).
3. **Expected:** `{"error":"Not Found","status":404}`.
4. Confirm legitimate access still works: **http://127.0.0.1:5051/api/dm/2**
   (admin → alice) returns the message with `200`.

---

## Fix V4 — Broken authentication (`alg=none`)

**Before** (`app.py` `verify_token()`): the `alg=none` branch skips verification.

```python
if header.get("alg") == "none":
    return payload.get("user")      # <-- no signature check
```

**After (minimal)** — never honor `alg=none`; always verify the HMAC:

```python
def verify_token(token):
    try:
        h_b64, p_b64, sig_b64 = token.split(".")
        expected = hmac.new(SECRET, f"{h_b64}.{p_b64}".encode(),
                            hashlib.sha256).digest()
        if not hmac.compare_digest(expected, b64url_decode(sig_b64)):
            return None
        return json.loads(b64url_decode(p_b64)).get("user")
    except Exception:
        return None
```

**After (better, what `app_fixed.py` does)** — drop hand-rolled tokens and use
Flask's signed session:

```python
SECRET_KEY = os.environ.get("CHIRP_SECRET_KEY") or secrets.token_hex(32)
SESSION_COOKIE_NAME = "chirp_fixed_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

def current_user():
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
```

**Check on the fixed build (browser):**

1. Sign out, open DevTools → **Console**, and plant the same forged token:

   ```javascript
   document.cookie = "session=eyJhbGciOiJub25lIiwidHlwIjoiQ0hJUlAifQ.eyJ1c2VyIjoiYWRtaW4ifQ.; path=/";
   ```

2. Open **http://127.0.0.1:5051/admin**.
3. **Expected:** **`403 Forbidden`** — the forged token is ignored (the fixed app
   reads `chirp_fixed_session`, a signed session). Tampering with a real
   `chirp_fixed_session` value also yields `403`.

---

## Fix V5 — Server-Side Template Injection

**Before** (`app.py` `profile()`): the bio is compiled as a template.

```python
bio_html = render_template_string(
    "<div class='bio'>" + (row["bio"] or "") + "</div>"
)
return render_template("profile.html", ..., bio_html=bio_html, ...)
```

**After** — pass the bio as *data* into a static template:

```python
return render_template(
    "profile.html", profile_user=row, bio=row["bio"] or "",
    tweets=tweets, user=current_user(),
)
```

```jinja
{# templates/profile.html — escaped automatically, no | safe #}
<div class="bio">{{ bio }}</div>
```

**Check on the fixed build (browser):**

1. Sign in, open **http://127.0.0.1:5051/settings**.
2. Set the **Bio** to `{{7*7}}` and click **Save changes**.
3. **Expected:** your profile shows the bio **literally** as `{{7*7}}` — it is
   **not** evaluated to `49`.

---

## Summary — before vs after (all five)

| # | GUI action | Vulnerable `:5000` | Fixed `:5051` |
|---|-----------|--------------------|----------------|
| V1 | Sign in with `admin' --` / `x` | signed in as admin | “Couldn’t sign you in. Invalid credentials.” |
| V2 | Post `<script>alert(document.cookie)</script>` | alert fires | shown as escaped text; nothing runs |
| V3 | Address bar `/api/dm/3` as alice | flag returned | `404 Not Found` |
| V4 | Set forged `session` cookie → `/admin` | flag | `403 Forbidden` |
| V5 | Save bio `{{7*7}}` → open profile | shows `49` | shows literal `{{7*7}}` |

And normal use still works on the fixed build: sign in with a real account, read
your **own** DM, post normally, and save plain text in your bio.

> Automated cross-check: `python verify_demo.py` drives both editions with a
> test client and prints one `PASS` line per vulnerability. Its V5 fixed-edition
> assertion fails because it compares Jinja's `&#34;` against Python's
> `html.escape` `&quot;` — a **test bug**, not a vulnerability; the fixed app
> does escape correctly.
