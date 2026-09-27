"""EVE SSO login and session cookies.

EVE SSO is the only way in: a user *is* an EVE character, which is also how their
fits stay tied to the character that owns them.

Flow (authorization code + PKCE):

1. ``GET /api/auth/login`` mints a ``state`` and a PKCE verifier, remembers them
   briefly, and redirects to EVE.
2. EVE redirects back to ``/api/auth/callback?code=...&state=...``.
3. We verify the state, swap the code for tokens, validate the JWT against the
   SSO's JWKS, and upsert the account row.
4. The SSO tokens are stored in that user's own saveddata database as an
   ``SsoCharacter``, so pyfa's own ESI code (skills, fittings, exports) works
   unchanged for that user from then on.
5. A signed cookie carries the account id; no server-side session table.

``PYFA_WEB_DEV_AUTH_BYPASS=1`` skips step 1-3 and logs in a fixed local account.
That is for development without registered SSO credentials and must never be set
on a public deployment.

What went wrong is told to the browser as one of the codes below; the reason itself
stays in the log, because EVE's answer to a failed exchange can quote a token.
``web/api/auth.py`` sends the code back and ``web/frontend/src/errors.ts`` writes the
sentence.
"""

import base64
import datetime
import hashlib
import json
import secrets
import threading
import time

import requests
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError
from logbook import Logger

import config as pyfaConfig

pyfalog = Logger(__name__)

#: How long a started login may take to come back from EVE
LOGIN_STATE_TTL = 900

#: Login states the browser is sent back with (see ``web/frontend/src/errors.ts``)
LOGIN_EXPIRED = "loginExpired"
LOGIN_CANCELLED = "loginCancelled"
LOGIN_FAILED = "loginFailed"
SSO_UNREACHABLE = "ssoUnreachable"

DEV_USER_CHARACTER_ID = 90000001
DEV_USER_NAME = "Dev Pilot"


class SsoError(RuntimeError):
    """A login that could not be completed.

    ``code`` is the only part the browser sees; ``str(error)`` is for the log.
    """

    def __init__(self, message, code=LOGIN_FAILED):
        super().__init__(message)
        self.code = code


class LoginState:
    def __init__(self, verifier, next_url, created_at):
        self.verifier = verifier
        self.next_url = next_url
        self.created_at = created_at


class LoginStateStore:
    """Remembers pending logins, keyed by the ``state`` parameter."""

    def __init__(self, ttl=LOGIN_STATE_TTL):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._states = {}

    def create(self, next_url):
        state = secrets.token_urlsafe(24)
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        with self._lock:
            self._purge()
            self._states[state] = LoginState(verifier, next_url, time.time())
        return state, verifier

    def consume(self, state):
        with self._lock:
            self._purge()
            entry = self._states.pop(state, None)
        if entry is None:
            raise SsoError(
                "Login state is unknown or expired. Start the login again.", LOGIN_EXPIRED)
        return entry

    def _purge(self):
        cutoff = time.time() - self.ttl
        for key in [k for k, v in self._states.items() if v.created_at < cutoff]:
            del self._states[key]


def code_challenge_for(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _describe(body, fallback, limit=300):
    """A short, log-safe description of an SSO answer.

    Never the whole body: for a good answer that would be somebody's token. A mapping is
    described by the error it carries, or by the keys it has instead of the token we
    asked for; anything else is truncated text.
    """
    if isinstance(body, dict):
        words = [str(body[key]) for key in ("error", "error_description") if body.get(key)]
        if words:
            return " ".join(words)[:limit]
        return "keys: {}".format(", ".join(sorted(body)) or "none")
    return (str(fallback or "").strip() or "(empty body)")[:limit]


def _signing_keys(keys, token):
    """The keys that could have signed ``token``, the named one first.

    ``kid`` decides it when the token names one: the key set may hold several keys, and
    the first is not necessarily the right one. Tokens without a key id (older ones) fall
    back to every RSA key in the set.

    The live key set holds an EC key next to the RSA one (CCP publishes both, for
    different signing algorithms), so the filter is not cosmetic: handing an ES256 key to
    an RS256 verification fails the login, and the symmetric entry a key set is allowed
    to carry must never be used to verify anything.
    """
    usable = [key for key in keys
              if key.get("kty") == "RSA" and key.get("alg", "RS256") == "RS256"]
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except JWTError:
        kid = None
    if kid:
        named = [key for key in usable if key.get("kid") == kid]
        if named:
            return named
    return usable


class SsoClient:
    """Thin client for EVE's SSO, with cached metadata and JWKS."""

    def __init__(self, sso_config, timeout=15):
        self.config = sso_config
        self.timeout = timeout
        self._lock = threading.Lock()
        self._metadata = None
        self._jwks = None
        self._fetched_at = 0

    @property
    def server(self):
        try:
            return pyfaConfig.supported_servers[self.config.server]
        except KeyError:
            raise SsoError(
                "Unknown EVE server {!r}; expected one of {}".format(
                    self.config.server, ", ".join(sorted(pyfaConfig.supported_servers)))
            )

    @property
    def issuer(self):
        return self.server.sso

    def _fresh(self):
        return self._metadata is not None and (time.time() - self._fetched_at) < 3600

    def metadata(self):
        with self._lock:
            if self._fresh():
                return self._metadata
            return self._load_metadata_unlocked()

    def jwks(self, refresh=False):
        """The signing keys, fetched once and then remembered.

        ``refresh`` throws the cached copy away first. A login does that when the
        token names a key id we do not hold: CCP rotates signing keys without notice,
        and the cached metadata is only refetched hourly.
        """
        with self._lock:
            if refresh:
                self._jwks = None
            if self._jwks is None:
                metadata = self._metadata or self._load_metadata_unlocked()
                self._jwks = self._fetch_jwks(metadata["jwks_uri"])
            return self._jwks

    def _load_metadata_unlocked(self):
        """Fetch and cache the SSO's endpoints. Call with ``self._lock`` held."""
        url = "https://{}/.well-known/oauth-authorization-server".format(self.issuer)
        body = self._get_json(url, "metadata")
        self._metadata = body
        # The keys are the other half of the same handshake; a new document may
        # point somewhere else, so they are dropped and fetched again on demand.
        self._jwks = None
        self._fetched_at = time.time()
        return body

    def _fetch_jwks(self, url):
        body = self._get_json(url, "signing keys")
        if not body.get("keys"):
            raise SsoError("EVE SSO returned an empty signing key set", SSO_UNREACHABLE)
        return body

    def _get_json(self, url, what):
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as ex:
            raise SsoError("Could not reach the EVE SSO {} endpoint: {}".format(what, ex),
                           SSO_UNREACHABLE)
        except ValueError as ex:
            raise SsoError("The EVE SSO {} document was not JSON: {}".format(what, ex),
                           SSO_UNREACHABLE)

    def authorize_url(self, redirect_uri, state, verifier):
        metadata = self.metadata()
        params = {
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "client_id": self.config.client_id,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "code_challenge": code_challenge_for(verifier),
            "code_challenge_method": "S256",
        }
        from urllib.parse import urlencode

        return "{}?{}".format(metadata["authorization_endpoint"], urlencode(params))

    def exchange_code(self, code, verifier, redirect_uri):
        metadata = self.metadata()
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.config.client_id,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        }
        if self.config.client_secret:
            payload["client_secret"] = self.config.client_secret
        try:
            response = requests.post(
                metadata["token_endpoint"],
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Host": self.issuer},
                timeout=self.timeout,
            )
        except requests.RequestException as ex:
            raise SsoError("Token exchange failed: {}".format(ex), SSO_UNREACHABLE)
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200 or not isinstance(body, dict):
            raise SsoError("Token exchange rejected by EVE (HTTP {}): {}".format(
                response.status_code, _describe(body, None)))
        # A 200 without a token is how a rejected grant comes back from some of CCP's
        # deployments, so the body is checked rather than only the status code.
        if not body.get("access_token"):
            raise SsoError("EVE's token response carried no access token: {}".format(
                _describe(body, None)))
        if not body.get("expires_in"):
            raise SsoError("EVE's token response carried no expiry: {}".format(
                _describe(body, None)))
        return body

    def validate_jwt(self, token):
        """Verify the access token and return its claims.

        With two attempts: a token that no key we hold signed may simply predate a key
        rotation, so the key set is fetched once more before the login is refused.
        """
        if not isinstance(token, str) or token.count(".") != 2:
            raise SsoError("EVE did not return a JWT access token")
        candidates = _signing_keys(self.jwks().get("keys") or [], token)
        for attempt in (0, 1):
            for key in candidates:
                try:
                    return jwt.decode(
                        token,
                        key,
                        algorithms=["RS256"],
                        # Tranquility claims `https://login.eveonline.com`; Serenity
                        # (login.evepc.163.com) publishes its issuer without a scheme.
                        issuer=[self.issuer, "https://{}".format(self.issuer)],
                        # CCP does not always set `aud`; pyfa ignores it for the same reason
                        options={"verify_aud": False},
                    )
                except ExpiredSignatureError as ex:
                    raise SsoError("The EVE token expired: {}".format(ex))
                except JWTClaimsError as ex:
                    raise SsoError("The EVE token's claims were rejected: {}".format(ex))
                except JWTError:
                    continue  # wrong key, or a token that was never signed by EVE
            if attempt == 0:
                # Nothing matched: the key set may predate a rotation, so it is fetched
                # once more before the login is refused.
                candidates = _signing_keys(self.jwks(refresh=True).get("keys") or [], token)
        raise SsoError("No RS256 signing key from the EVE SSO matched the token")

    def character_from_claims(self, claims):
        """Extract (character id, name) from validated SSO claims.

        Only character tokens are accepted. A corporation or alliance token has
        the same shape (``CORPORATION:EVE:123``) and would otherwise be taken for
        a character, tying an account to the wrong id.
        """
        sub = claims.get("sub") or ""
        parts = sub.split(":")
        if len(parts) != 3 or parts[0] != "CHARACTER" or parts[1] != "EVE":
            raise SsoError("Unexpected SSO subject claim: {!r}".format(sub))
        try:
            character_id = int(parts[2])
        except ValueError:
            raise SsoError("SSO subject does not end in a character id: {!r}".format(sub))
        return character_id, claims.get("name") or "Unknown pilot"


class SessionTokens:
    """Signs and verifies the session cookie."""

    def __init__(self, secret_key, max_age, salt="pyfa-session"):
        self.serializer = URLSafeTimedSerializer(secret_key, salt=salt)
        self.max_age = max_age

    def issue(self, user_id):
        return self.serializer.dumps({"user_id": user_id})

    def read(self, value):
        """Return the user id in ``value``, or None when it is unusable."""
        if not value:
            return None
        try:
            data = self.serializer.loads(value, max_age=self.max_age)
        except SignatureExpired:
            pyfalog.debug("Session cookie expired")
            return None
        except BadSignature:
            pyfalog.warning("Rejected a session cookie with a bad signature")
            return None
        return data.get("user_id")


def store_sso_character(user_data, character_id, character_name, server_name, token_response):  # noqa: ARG001
    """Persist the SSO tokens as an SsoCharacter inside the user's own database.

    pyfa's ESI code reads the character back out of the saveddata database of whoever is
    asking, so this is all it takes for skills, fittings import and fitting export to work
    for that user. ``user_data`` is not used directly: it is what has the session bound,
    and passing it keeps that requirement in sight at the call site.

    The row is found by EVE character id and not by the row's own id, because
    ``ssoCharacter`` is unique on ``(client, server, characterID)``: signing in again has
    to refresh the tokens on the row that is already there, not add a second one.
    """
    import eos.db
    from eos.saveddata.ssocharacter import SsoCharacter
    from service.esiAccess import EsiAccess

    client_hash = pyfaConfig.getClientSecret()
    session = eos.db.saveddata_session
    character = session.query(SsoCharacter).filter(
        SsoCharacter.characterID == int(character_id),
        SsoCharacter.client == client_hash,
        SsoCharacter.server == server_name,
    ).first()
    if character is None:
        character = SsoCharacter(character_id, character_name, client_hash, server_name)
    else:
        character.characterName = character_name
    EsiAccess.update_token(character, token_response)
    eos.db.save(character)
    eos.db.commit()
    return character


def dev_login_claims():
    """Claims used by the development bypass login."""
    expires = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + datetime.timedelta(hours=1)
    return {
        "sub": "CHARACTER:EVE:{}".format(DEV_USER_CHARACTER_ID),
        "name": DEV_USER_NAME,
        "scp": [],
        "exp": int(expires.timestamp()),
    }


def describe_claims(claims):
    """Small helper for logs and the ``/api/auth/me`` payload."""
    return {
        "sub": claims.get("sub"),
        "name": claims.get("name"),
        "owner": claims.get("owner"),
        "scopes": claims.get("scp") or [],
    }


def debug_state_dump(store):  # pragma: no cover - used by the dev tools page
    return json.dumps({k: v.next_url for k, v in store._states.items()}, indent=2)

