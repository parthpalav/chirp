# Chirp — Patches

How to fix each planted vulnerability. The guiding principle appears under each.

---

## V1 — SQL Injection

**Root cause:** string-built SQL. **Fix:** parameterized queries, and never
store plaintext passwords — hash them and compare the hash.

```python
# Before
query = ("SELECT * FROM users WHERE username = '%s' AND password = '%s'"
         % (username, password))
row = db.execute(query).fetchone()

# After
row = db.execute(
    "SELECT * FROM users WHERE username = ?", (username,)
).fetchone()
if row and check_password_hash(row["password"], password):
    ...   # from werkzeug.security import generate_password_hash, check_password_hash
```

**Principle:** separate code from data. Let the driver bind values; never
interpolate input into a query string.

---

## V2 — Stored XSS

**Root cause:** output rendered with `| safe`, disabling escaping. **Fix:**
remove `| safe` so Jinja auto-escapes; if limited HTML is required, sanitize
with an allowlist (e.g. `bleach`) on input.

```jinja
{# Before #}
<div>{{ t['body'] | safe }}</div>

{# After — Jinja escapes < > & " ' automatically #}
<div>{{ t['body'] }}</div>
```

Defense in depth: send a Content-Security-Policy header
(`default-src 'self'; script-src 'self'`) to block inline scripts.

**Principle:** escape on output, contextually; treat all stored content as
untrusted when rendering.

---

## V3 — IDOR

**Root cause:** object fetched by id with no ownership/authorization check.
**Fix:** scope the query to the current user (and/or verify after fetch).

```python
# After
dm = db.execute(
    "SELECT * FROM dms WHERE id = ? AND (sender = ? OR recipient = ?)",
    (dm_id, user["username"], user["username"]),
).fetchone()
if not dm:
    abort(404)   # 404 (not 403) avoids confirming the row exists
```

**Principle:** authenticate *and* authorize — every object access must be
checked against who is asking. Don't rely on ids being unguessable.

---

## V4 — Broken authentication (`alg=none`)

**Root cause:** the server trusts the client-supplied `alg`. **Fix:** pin the
algorithm server-side and always require a valid signature. Better: use a
vetted library (PyJWT) with an explicit `algorithms=[...]` allowlist.

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

Also: use a long, random, secret signing key (not a hard-coded string), and
consider short token lifetimes.

**Principle:** the server decides the algorithm, not the token. Prefer audited
libraries over hand-rolled crypto.

---

## V5 — Server-Side Template Injection

**Root cause:** user input compiled as a template via `render_template_string`.
**Fix:** never build templates from user input. Pass the bio as *data* into a
static template, where it is auto-escaped like any other variable.

```python
# Before
bio_html = render_template_string("<div class='bio'>" + row["bio"] + "</div>")
return render_template("profile.html", bio_html=bio_html, ...)

# After — pass bio as a context variable; drop `| safe` in the template
return render_template("profile.html", bio=row["bio"], ...)
```

```jinja
{# profile.html — escaped automatically #}
<div class="bio">{{ bio }}</div>
```

**Principle:** templates are code. User input is data and must never be
concatenated into, or evaluated as, a template.

---

## General hardening checklist

- Parameterize every query (V1).
- Escape all output; add a CSP (V2).
- Authorize every object access, not just authenticate (V3).
- Pin crypto algorithms; use vetted auth libraries; strong random secrets (V4).
- Never treat user input as code/templates (V5).
- Hash passwords (`generate_password_hash`); don't store plaintext.
- Turn off `debug=True` in anything but local dev (it exposes the Werkzeug
  console / RCE).
- Set cookies `HttpOnly`, `Secure`, `SameSite`.
