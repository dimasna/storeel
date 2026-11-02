"""Who may see and change a reel or a novel, without a login.

A browser gets a random token in an HttpOnly cookie on its first visit, and the reels and novels
it makes store a hash of that token as their owner. With private projects on (the hosted
studio), a browser sees and changes only what it owns, plus the showcase: reels and novels
everyone may watch and nobody may change. With it off (the studio on your own machine)
everything stays open, as before.

The token is a bearer secret: anyone holding it is that owner. It never leaves the cookie (the
API only ever sees its hash), the cookie is HttpOnly so page scripts cannot read it, and Secure
when the studio is served over https.
"""

from __future__ import annotations

import hashlib
import re
import secrets

from starlette.requests import Request

COOKIE = "storeel_owner"
MAX_AGE = 60 * 60 * 24 * 30  # 30 days: well past the 24 hours a reel is kept
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")

# The paths that name one reel, one novel, or one job (whose reel is checked).
PROJECT_PATH = re.compile(r"^/api/projects/([0-9a-f]{32})(?:/|$)")
NOVEL_PATH = re.compile(r"^/api/novels/([0-9a-f]{32})(?:/|$)")
JOB_PATH = re.compile(r"^/api/jobs/([0-9a-f]{32})(?:/|$)")


def owner_of(token: str) -> str:
    """What a reel or a novel stores: a hash of the token, never the token itself."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def token_from(request: Request) -> tuple[str, bool]:
    """The browser's token, and whether it is new (so the response must set the cookie)."""
    token = request.cookies.get(COOKIE, "")
    if TOKEN_RE.match(token):
        return token, False
    return secrets.token_hex(32), True


def served_over_https(request: Request) -> bool:
    # Behind Modal's proxy the app may see plain http; the proxy says what the browser used.
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def allowed(owner: str, item_owner: str | None, *, private: bool, showcase: bool, write: bool) -> str:
    """'ok', 'read-only' (a showcase asked to change) or 'hidden' (someone else's)."""
    if showcase:
        return "read-only" if write else "ok"
    if not private or item_owner == owner:
        return "ok"
    return "hidden"
