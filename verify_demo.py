"""Exercise the before/after demo using temporary databases, without a server."""
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import shutil
import tempfile

import app as vulnerable
import app_fixed as fixed
from seed import seed_database


class FormTokens(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "csrf_token":
            self.token = attrs["value"]


def csrf(client, path):
    parser = FormTokens()
    parser.feed(client.get(path).text)
    return parser.token


def post(client, path, data, *, fixed_mode=False, form_path=None):
    data = dict(data)
    if fixed_mode:
        data["csrf_token"] = csrf(client, form_path or path)
    return client.post(path, data=data, follow_redirects=True)


def login(client, username="bob", password="hunter2", *, fixed_mode=False):
    return post(client, "/login", {"username": username, "password": password}, fixed_mode=fixed_mode)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run():
    original_paths = vulnerable.DB_PATH, fixed.DB_PATH
    try:
        with tempfile.TemporaryDirectory(prefix="chirp-demo-check-") as folder:
            for module, hardened, name in ((vulnerable, False, "vulnerable"), (fixed, True, "fixed")):
                module.DB_PATH = str(Path(folder) / f"{name}.db")
                module.app.config["TESTING"] = True
                seed_database(module.DB_PATH, fixed=hardened)
                shutil.copyfile(module.DB_PATH, str(Path(folder) / f"{name}-seed.db"))

            for module, hardened in ((vulnerable, False), (fixed, True)):
                edition = "fixed" if hardened else "vulnerable"
                with module.app.test_client() as client:
                    # V1: valid CSRF is included in the fixed attempt, isolating SQLi.
                    bad = login(client, "bob", "incorrect", fixed_mode=hardened)
                    check('role="alert"' in bad.text, f"{edition}: incorrect passwords must fail")
                    bypass = login(client, "admin' --", "x", fixed_mode=hardened)
                    check(('role="alert"' in bypass.text) == hardened, f"{edition}: V1 unexpected result")
                    check(client.get("/admin").status_code == (403 if hardened else 200), f"{edition}: V1 authorization")
                print(f"PASS V1 [{edition}]: SQLi {'rejected with valid CSRF' if hardened else 'bypasses login'}")

                with module.app.test_client() as client:
                    check(login(client, fixed_mode=hardened).status_code == 200, "Bob login")
                    check(client.get("/api/dm/1").status_code == 200, "Bob can read DM 1")
                    check(client.get("/api/dm/3").status_code == 200, "Bob can read DM 3")
                    forbidden = client.get("/api/dm/2")
                    check(forbidden.status_code == (404 if hardened else 200), f"{edition}: V3 unexpected result")
                    if not hardened:
                        check(forbidden.json["message"] == "FLAG{idor_lets_you_read_my_dms}", "IDOR flag")
                    check(client.get("/api/dm/99999").status_code == 404, "Missing DM returns 404")
                print(f"PASS V3 [{edition}]: Bob {'cannot' if hardened else 'can'} read admin-to-Alice DM; legitimate access works")

                forged = vulnerable.b64url(b'{"alg":"none","typ":"CHIRP"}') + "." + vulnerable.b64url(b'{"user":"admin"}') + "."
                with module.app.test_client() as client:
                    cookie_name = module.app.config["SESSION_COOKIE_NAME"]
                    client.set_cookie(cookie_name, forged)
                    check(client.get("/admin").status_code == (403 if hardened else 200), f"{edition}: V4 unexpected result")
                if hardened:
                    with module.app.test_client() as client:
                        client.set_cookie("session", forged)
                        check(client.get("/admin").status_code == 403, "Old custom tokens must not authenticate")
                    with module.app.test_client() as client:
                        login(client, "admin", "S3cr3t_@dm1n_2026", fixed_mode=True)
                        cookie = client.get_cookie("chirp_fixed_session").value
                        parts = cookie.split(".")
                        parts[-1] = ("A" if parts[-1][0] != "A" else "B") + parts[-1][1:]
                        client.set_cookie("chirp_fixed_session", ".".join(parts))
                        check(client.get("/admin").status_code == 403, "Tampered signed sessions must fail")
                print(f"PASS V4 [{edition}]: unsigned admin token {'rejected; signed-session tampering also rejected' if hardened else 'accepted'}")

                with module.app.test_client() as client:
                    login(client, "alice", "password123", fixed_mode=hardened)
                    response = post(client, "/settings", {"bio": "Demo proof: {{7*7}}"}, fixed_mode=hardened)
                    expected = "Demo proof: {{7*7}}" if hardened else "Demo proof: 49"
                    check(expected in response.text, f"{edition}: V5 unexpected result")
                    check("Your profile has been updated." in response.text, "Bio save feedback")
                    html_bio = '<img src="x" onerror="alert(1)">'
                    response = post(client, "/settings", {"bio": html_bio}, fixed_mode=hardened)
                    check((escape(html_bio) if hardened else html_bio) in response.text, "Bio escaping")
                print(f"PASS V5 [{edition}]: bio expression {'stays literal; HTML is escaped' if hardened else 'evaluates to 49'}")

                with module.app.test_client() as client:
                    login(client, "alice", "password123", fixed_mode=hardened)
                    payload = "<script>alert('CHIRP XSS proof')</script>"
                    response = post(client, "/tweet", {"body": payload}, fixed_mode=hardened, form_path="/")
                    expected = escape(payload) if hardened else payload
                    check(expected in response.text, f"{edition}: V2 feed escaping")
                    check(expected in client.get("/user/alice").text, f"{edition}: V2 profile escaping")
                    check("Your post is now on the feed." in response.text, "Post success feedback")
                    if hardened:
                        check("script-src 'self'" in response.headers["Content-Security-Policy"], "CSP")
                        check(client.post("/tweet", data={"body": "no CSRF"}).status_code == 400, "CSRF rejection")
                        check(client.post("/tweet", data={"body": "Unicode", "csrf_token": "你好"}).status_code == 400, "Invalid Unicode CSRF must not cause 500")
                        empty = post(client, "/tweet", {"body": "   "}, fixed_mode=True, form_path="/")
                        check(empty.status_code == 400, "Empty post rejected")
                        token = csrf(client, "/")
                        check(client.post("/logout", data={"csrf_token": token}, follow_redirects=True).status_code == 200, "Fixed logout")
                    else:
                        client.get("/logout")
                    check(client.get("/api/dm/1").status_code == 401, "Signed-out DM access")
                print(f"PASS V2 [{edition}]: stored script {'escaped on feed and profiles, with CSP' if hardened else 'rendered as executable markup'}")

                with module.app.test_client() as client:
                    response = login(client, "admin", "S3cr3t_@dm1n_2026", fixed_mode=hardened)
                    check(response.status_code == 200, "Legitimate admin login")
                    check(client.get("/admin").status_code == 200, "Legitimate admin access")
                    check(client.get("/settings").status_code == 200, "Settings renders")
                    for asset in ("style.css", "ui.js", "timeline.svg", "fonts/IBMPlexSans-Regular.woff2"):
                        check(client.get(f"/static/{asset}").status_code == 200, asset)
                    if hardened:
                        cookie = response.headers.getlist("Set-Cookie")
                        # Redirect responses contain the cookie; follow_redirects retains history.
                        cookie = response.history[0].headers.getlist("Set-Cookie") or cookie
                        check(any("HttpOnly" in value and "SameSite=Lax" in value for value in cookie), "Cookie flags")
                        check(not module.app.debug, "Fixed debug mode must be off")
                print(f"PASS controls [{edition}]: real logins, pages, assets, and sign-out remain functional")

            print("\nAll five demonstrations match the expected before/after results.")
            print("Existing project databases were not changed. Browser XSS execution still needs the classroom popup check.")
    finally:
        vulnerable.DB_PATH, fixed.DB_PATH = original_paths


if __name__ == "__main__":
    run()
