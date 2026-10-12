# Chirp — Vulnerable Social App (CTF)

A tiny Twitter-like app (Flask + SQLite) with **5 intentional vulnerabilities**
for CTF / security-training use.

> ⚠️ Training target only. It is intentionally insecure. Run it offline on
> localhost. Never expose it publicly or load real data into it.

## Run it

```bash
cd chirp
python3 seed.py      # creates chirp.db with demo users + flags
python3 app.py       # serves on http://127.0.0.1:5000
```

Demo accounts (also in `seed.py`):

| user  | password          | note          |
|-------|-------------------|---------------|
| admin | S3cr3t_@dm1n_2026 | has `/admin`  |
| alice | password123       | regular user  |
| bob   | hunter2           | regular user  |

## The 5 vulnerabilities

| # | Class | Location | Flag |
|---|-------|----------|------|
| V1 | SQL Injection | `/login` | — (auth bypass) |
| V2 | Stored XSS | tweet body on `/` | — |
| V3 | IDOR | `/api/dm/<id>` | `FLAG{idor_lets_you_read_my_dms}` |
| V4 | Broken auth (JWT `alg=none`) | session cookie → `/admin` | `FLAG{alg_none_made_you_admin}` |
| V5 | Server-Side Template Injection | profile bio → `/user/<name>` | — (RCE primitive) |

Full exploit walkthroughs: [docs/VULNERABILITIES.md](docs/VULNERABILITIES.md)
Fixes for each: [docs/PATCHES.md](docs/PATCHES.md)

## Files

```
chirp/
  app.py            # the app (every vuln marked with a V# comment)
  seed.py           # builds/seeds chirp.db
  templates/        # Jinja templates
  static/           # shared stylesheet, SVG favicon, local IBM Plex fonts
  docs/
    VULNERABILITIES.md
    PATCHES.md
```

## Interface

The interface uses a Swiss modern layout inspired by IBM Carbon: a neutral
product shell, aligned columns, square controls, and blue primary actions.
IBM Plex Sans and Mono are bundled locally, so the UI needs no font CDN,
JavaScript framework, or frontend build step.

Shared styling lives in `static/style.css`; reusable icons and post markup
live in `templates/components.html`. Profiles include each user's posts,
and the feed's community list is populated from the database.

See [docs/DESIGN.md](docs/DESIGN.md) for the visual system and reference links.
The five intentional training vulnerabilities remain in place.
