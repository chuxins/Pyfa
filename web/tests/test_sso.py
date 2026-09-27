"""EVE SSO login, end to end.

The parts of a login that can be wrong without anyone noticing: the state that comes
back from EVE, the token that comes with it, and the rows it leaves behind -- the
account, and the ``SsoCharacter`` in the pilot's own database that pyfa's ESI code
looks up later.

Nothing here talks to CCP. A private key is generated per run and a stub answers the two
documents and the one endpoint a login uses, so the checks that matter -- signature, key
id, issuer, expiry, single-use state -- really run. Serenity's shape is covered as well:
NetEase publishes its issuer without a scheme, CCP with an ``https://`` URL.
"""

import base64
import hashlib
import json
import time
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests as realRequests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

import web.auth as webAuth
import web.main as webMain
from web.api.auth import CALLBACK_PATH
from web.auth import SsoClient
from web.config import SsoConfig
from web.tests.conftest import next_character_id

#: What the live SSO answers at /.well-known/oauth-authorization-server (fetched from
#: login.eveonline.com), cut down to the fields a login uses.
TRANQUILITY = {
    "issuer": "https://login.eveonline.com",
    "authorization_endpoint": "https://login.eveonline.com/v2/oauth/authorize",
    "token_endpoint": "https://login.eveonline.com/v2/oauth/token",
    "jwks_uri": "https://login.eveonline.com/oauth/jwks",
    # CCP advertises this; the desktop client relies on it too
    "code_challenge_methods_supported": ["S256"],
}

#: login.evepc.163.com, the same document except for the issuer, which has no scheme
SERENITY = {
    "issuer": "login.evepc.163.com",
    "authorization_endpoint": "https://login.evepc.163.com/v2/oauth/authorize",
    "token_endpoint": "https://login.evepc.163.com/v2/oauth/token",
    "jwks_uri": "https://login.evepc.163.com/oauth/jwks",
}

#: Both key sets publish an EC key next to the RSA one (fetched from the live endpoints);
#: the fields that matter here are the algorithm and the key type.
EC_KEY = {
    "alg": "ES256", "kty": "EC", "use": "sig", "crv": "P-256",
    "kid": "8878a23f-2489-4045-989e-4d2f3ec1ae1a",
    "x": "PatzB2HJzZOzmqQyYpQYqn3SAXoVYWrZKmMgJnfK94I",
    "y": "qDb1kUd13fRTN2UNmcgSoQoyqeF_C1MsFlY_a87csnY",
}

#: A key set is allowed to carry a symmetric entry. Nothing may ever verify with it.
SYMMETRIC_KEY = {"alg": "HS256", "kty": "oct", "use": "sig", "kid": "a-shared-secret",
                 "k": "c2VjcmV0"}


def _b64(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class _Key:
    """A signing key and the JWK that publishes it, the way the SSO publishes one."""

    def __init__(self, kid):
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pem = self.private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        numbers = self.private.public_key().public_numbers()
        self.jwk = {
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "kid": kid,
            "n": _b64(numbers.n),
            "e": _b64(numbers.e),
        }

    def token(self, claims, kid=True):
        headers = {"kid": self.kid} if kid else {}
        return jwt.encode(claims, self.pem, algorithm="RS256", headers=headers)


@pytest.fixture(scope="module")
def keyring():
    """Three keys: the one EVE signs with, one it never publishes, and a rotated one."""
    return {
        "primary": _Key("pyfa-test-1"),
        "other": _Key("pyfa-test-2"),
        "rotated": _Key("pyfa-test-3"),
    }


def claims(character_id=None, name="Sso Tester", issuer=TRANQUILITY["issuer"], expires_in=1200):
    now = int(time.time())
    return {
        "sub": "CHARACTER:EVE:{}".format(character_id or next_character_id()),
        "name": name,
        "owner": "sso-owner-hash",
        "scp": ["esi-skills.read_skills.v1", "esi-fittings.write_fittings.v1"],
        "iss": issuer,
        "iat": now,
        "exp": now + expires_in,
    }


def character_id_of(token_claims):
    return int(token_claims["sub"].split(":")[-1])


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("no JSON in this answer")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise realRequests.HTTPError("HTTP {} for a test response".format(self.status_code))


class StubSso:
    """Answers what ``SsoClient`` asks for, and remembers what it was asked.

    ``rotate_to`` publishes a second key set from the *second* JWKS fetch on, which is
    what a key rotation looks like to a server that has been running for a while.
    """

    # ``web/auth.py`` catches this, so the stub has to expose it
    RequestException = realRequests.RequestException

    def __init__(self, published, metadata=TRANQUILITY):
        self.published = list(published)
        self.metadata = metadata
        self.token_response = None
        self.token_status = 200
        self.rotate_to = None
        self.fail = None
        self.calls = []
        self.metadata_fetches = 0
        self.jwks_fetches = 0

    def get(self, url, timeout=None, **kwargs):  # noqa: ARG002 - the signature of requests.get
        self.calls.append(("GET", url, None))
        if self.fail is not None:
            raise self.fail
        if url.endswith("/.well-known/oauth-authorization-server"):
            self.metadata_fetches += 1
            return _Response(200, self.metadata)
        if url.endswith("/oauth/jwks"):
            self.jwks_fetches += 1
            if self.rotate_to is not None and self.jwks_fetches > 1:
                return _Response(200, {"keys": [self.rotate_to.jwk]})
            return _Response(200, {"keys": list(self.published)})
        raise AssertionError("unexpected SSO GET: {}".format(url))

    def post(self, url, data=None, headers=None, timeout=None, **kwargs):  # noqa: ARG002
        self.calls.append(("POST", url, data))
        self.headers = headers
        if self.fail is not None:
            raise self.fail
        if url != self.metadata["token_endpoint"]:
            raise AssertionError("unexpected SSO POST: {}".format(url))
        return _Response(self.token_status, self.token_response)

    def token_payload(self):
        return next(data for method, _, data in self.calls if method == "POST")


def token_response(key, token_claims, expires_in=1200):
    """The shape EVE answers a successful exchange with."""
    return {
        "access_token": key.token(token_claims),
        "expires_in": expires_in,
        "refresh_token": "a-refresh-token",
        "token_type": "Bearer",
    }


@pytest.fixture
def sso(app_state, monkeypatch, keyring):
    """Point the running app at the stub SSO for one test, bypass switched off."""
    stub = StubSso([keyring["primary"].jwk])
    monkeypatch.setattr(webAuth, "requests", stub)
    config = SsoConfig(server="Tranquility", client_id="test-client-id", client_secret="")
    monkeypatch.setattr(app_state.config, "sso", config)
    monkeypatch.setattr(app_state.config, "dev_auth_bypass", False)
    monkeypatch.setattr(app_state, "sso", SsoClient(config))
    return stub


def begin_login(client, next_url="/"):
    """Start a login the way the sign-in link does, and unpack the authorize URL."""
    response = client.get("/api/auth/login", params={"next": next_url}, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith(TRANQUILITY["authorization_endpoint"] + "?"), location
    return parse_qs(urlsplit(location).query)


def come_back(client, authorize_query, code="an-authorization-code"):
    """Come back from EVE the way the browser does."""
    return client.get(
        "/api/auth/callback",
        params={"code": code, "state": authorize_query["state"][0]},
        follow_redirects=False,
    )


def stored_characters(app_state, user_id):
    """The SsoCharacter rows in the pilot's own database -- the ones ESI will use."""
    import eos.db
    from eos.saveddata.ssocharacter import SsoCharacter

    with app_state.registry.acquire(user_id):
        rows = eos.db.saveddata_session.query(SsoCharacter).all()
        return {
            row.characterID: {
                "name": row.characterName,
                "server": row.server,
                "accessToken": row.accessToken,
                "refreshToken": row.refreshToken,
            }
            for row in rows
        }


# -- the flow ---------------------------------------------------------------------------


def test_the_sign_in_link_sends_the_browser_to_eve(client, app_state, sso):  # noqa: ARG001 - the fixture wires the app up
    """PKCE, the configured scopes, the registered callback and a fresh state."""
    query = begin_login(client, next_url="/fits/7")

    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["test-client-id"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [app_state.config.callback_url()]
    assert query["redirect_uri"][0].endswith("/api/auth/callback")
    assert query["scope"][0].split() == list(app_state.config.sso.scopes)
    assert len(query["state"][0]) > 20
    # The verifier stays on the server: what EVE sees is its hash
    assert "code_verifier" not in query
    assert len(query["code_challenge"][0]) == 43


def test_a_callback_without_a_path_is_forwarded_to_the_callback_route(client):
    """A registration that stops at the origin lands on the app page, not on the route.

    ``http://127.0.0.1:8080/`` is a shape EVE accepts, and it puts ``code`` and ``state``
    in the SPA's own query string: dropped there, a real login would look like a page that
    simply reloaded. The answer is handed on with its query string intact instead.
    """
    response = client.get(
        "/",
        params={"code": "an-authorization-code", "state": "a-state"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/api/auth/callback?code=an-authorization-code&state=a-state"
    )


def test_a_cancelled_login_arriving_at_the_app_page_reaches_the_callback(client):
    """The result of that forward is the real callback: it answers as it always would."""
    response = client.get(
        "/",
        params={"error": "access_denied", "state": "a-state"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert dict(response.url.params) == {"sso_error": "loginCancelled"}


def test_the_app_page_answers_for_itself(client):
    """Only an OAuth answer is forwarded; everything else stays with the app."""
    for params in ({"sso_error": "loginExpired"}, {"state": "no code and no error"}):
        response = client.get("/", params=params)

        assert response.status_code == 200, response.text
        assert "text/html" in response.headers["content-type"]


def test_the_callback_path_has_to_name_a_path_the_server_answers(app_state):
    """A typo there is a login that fails with no explanation, so it is reported early."""
    config = app_state.config
    assert config.sso.callback_path == CALLBACK_PATH, "the default has to be the mounted path"

    for path in ("/", ""):
        assert webMain._callback_path_warning(
            replace(config, sso=replace(config.sso, callback_path=path))
        ) is None

    warning = webMain._callback_path_warning(
        replace(config, sso=replace(config.sso, callback_path="/callback/"))
    )
    assert warning is not None
    assert "'/callback/'" in warning
    assert CALLBACK_PATH in warning


def test_callback_signs_the_pilot_in_and_returns_to_the_page_asked_for(client, sso, keyring):
    token_claims = claims()
    sso.token_response = token_response(keyring["primary"], token_claims)

    authorize = begin_login(client, next_url="/fits/7")
    response = come_back(client, authorize)

    assert response.status_code == 303
    assert response.headers["location"] == "/fits/7"
    assert client.cookies.get("pyfa_session")

    me = client.get("/api/auth/me").json()
    assert me["authenticated"] is True
    assert me["user"]["characterId"] == character_id_of(token_claims)
    assert me["user"]["characterName"] == token_claims["name"]


def test_the_account_remembers_who_signed_in(client, app_state, sso, keyring):
    token_claims = claims()
    sso.token_response = token_response(keyring["primary"], token_claims)
    come_back(client, begin_login(client))

    user = app_state.users.get_by_character_id(character_id_of(token_claims))
    assert user is not None
    assert user.character_name == token_claims["name"]
    assert user.owner_hash == "sso-owner-hash"
    assert user.scopes.split() == token_claims["scp"]
    assert user.last_login_at is not None
    assert user.created_at is not None


def test_the_sso_tokens_land_in_the_pilots_own_database(client, app_state, sso, keyring):
    """What makes skills and fittings import work after a login, with no second one."""
    token_claims = claims()
    sso.token_response = token_response(keyring["primary"], token_claims)
    come_back(client, begin_login(client))

    user = app_state.users.get_by_character_id(character_id_of(token_claims))
    characters = stored_characters(app_state, user.id)

    assert list(characters) == [character_id_of(token_claims)], "keyed by EVE character id"
    character = characters[character_id_of(token_claims)]
    assert character is not None
    assert character["name"] == token_claims["name"]
    assert character["server"] == "Tranquility"
    assert character["accessToken"] == sso.token_response["access_token"]
    # Encrypted, so stored -- that is how pyfa's ESI code refreshes the token later
    assert character["refreshToken"] not in (None, "", "a-refresh-token")


def test_signing_in_again_refreshes_the_same_row(client, app_state, sso, keyring):
    """``ssoCharacter`` is unique per (client, server, character id): no duplicates, and
    the tokens are the ones from the latest login."""
    first = claims()
    character_id = character_id_of(first)
    sso.token_response = token_response(keyring["primary"], first)
    come_back(client, begin_login(client))

    second = claims(character_id=character_id, expires_in=9999)
    sso.token_response = token_response(keyring["primary"], second)
    come_back(client, begin_login(client))

    user = app_state.users.get_by_character_id(character_id)
    characters = stored_characters(app_state, user.id)
    assert list(characters) == [character_id]
    assert characters[character_id]["accessToken"] == sso.token_response["access_token"]


def test_a_failed_login_leaves_no_account_behind(client, app_state, sso, keyring):
    token_claims = claims()
    sso.token_response = token_response(keyring["other"], token_claims)  # not EVE's key
    come_back(client, begin_login(client))

    assert app_state.users.get_by_character_id(character_id_of(token_claims)) is None


def test_a_state_can_only_be_used_once(client, sso, keyring):
    sso.token_response = token_response(keyring["primary"], claims())
    authorize = begin_login(client)
    assert come_back(client, authorize).headers["location"] != "/?sso_error=loginExpired"

    replay = come_back(client, authorize)
    assert replay.status_code == 303, "a replayed state must not be a 500"
    assert replay.headers["location"] == "/?sso_error=loginExpired"


def test_a_stale_state_comes_back_as_an_expired_login(client, app_state, sso, keyring):
    sso.token_response = token_response(keyring["primary"], claims())
    authorize = begin_login(client)
    entry = app_state.login_states._states[authorize["state"][0]]
    entry.created_at -= app_state.login_states.ttl + 1

    response = come_back(client, authorize)
    assert response.status_code == 303
    assert response.headers["location"] == "/?sso_error=loginExpired"


def test_an_unsafe_next_target_is_dropped(client, sso, keyring):
    sso.token_response = token_response(keyring["primary"], claims())
    response = come_back(client, begin_login(client, next_url="//evil.example.com"))
    assert response.headers["location"] == "/"


# -- the ways it goes wrong -------------------------------------------------------------


def test_a_rejected_token_exchange_comes_back_with_a_code(client, app_state, sso, keyring):
    sso.token_status = 400
    sso.token_response = {"error": "invalid_grant", "error_description": "the code expired"}

    response = come_back(client, begin_login(client))

    assert response.status_code == 303
    assert response.headers["location"] == "/?sso_error=loginFailed"
    assert client.get("/api/auth/me").json()["authenticated"] is False
    # The reason is in the log, not on the wire: it can quote a token
    assert "invalid_grant" not in response.headers["location"]


def test_a_token_that_no_published_key_signed_is_refused(client, sso, keyring):
    sso.token_response = token_response(keyring["other"], claims())
    response = come_back(client, begin_login(client))
    assert response.headers["location"] == "/?sso_error=loginFailed"


def test_a_login_declined_at_eve_comes_back_as_cancelled(client, sso):
    """Pressing "cancel" at EVE's consent page answers with ``?error=access_denied`` and no
    code at all: the browser must not be handed an API error for doing as it was told."""
    authorize = begin_login(client)

    response = client.get(
        "/api/auth/callback",
        params={"error": "access_denied", "state": authorize["state"][0]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?sso_error=loginCancelled"


def test_an_error_eve_reports_itself_is_a_failed_login(client, sso):
    response = client.get(
        "/api/auth/callback",
        params={"error": "server_error", "state": "a-state-eve-invented"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?sso_error=loginFailed"


def test_a_callback_without_a_code_is_not_a_422(client, sso):
    """However the browser got here, it is sent back into the app, never handed JSON."""
    response = client.get("/api/auth/callback", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?sso_error=loginExpired"

    only_state = client.get(
        "/api/auth/callback", params={"state": "whatever"}, follow_redirects=False)
    assert only_state.status_code == 303
    assert only_state.headers["location"] == "/?sso_error=loginExpired"


def test_an_expired_token_is_refused(client, sso, keyring):
    sso.token_response = token_response(keyring["primary"], claims(expires_in=-60))
    response = come_back(client, begin_login(client))
    assert response.headers["location"] == "/?sso_error=loginFailed"


@pytest.mark.parametrize("subject", [
    "CORPORATION:EVE:98000001",
    "ALLIANCE:EVE:99000001",
    "CHARACTER:EVE:not-a-number",
    "",
])
def test_only_character_tokens_are_accepted(client, sso, keyring, subject):
    token_claims = claims()
    token_claims["sub"] = subject
    sso.token_response = token_response(keyring["primary"], token_claims)
    response = come_back(client, begin_login(client))
    assert response.headers["location"] == "/?sso_error=loginFailed"


def test_a_200_without_a_token_is_not_a_login(client, app_state, sso):
    sso.token_status = 200
    sso.token_response = {"error": "invalid_grant"}
    response = come_back(client, begin_login(client))
    assert response.headers["location"] == "/?sso_error=loginFailed"
    assert client.get("/api/auth/me").json()["authenticated"] is False


def test_an_unreachable_sso_says_so(client, sso):
    authorize = begin_login(client)
    sso.fail = realRequests.ConnectionError("the network is gone")
    response = come_back(client, authorize)
    assert response.headers["location"] == "/?sso_error=ssoUnreachable"


def test_a_rotated_signing_key_is_picked_up_without_a_restart(client, sso, keyring):
    """CCP rotates keys without notice; the cached key set must not lock everyone out."""
    sso.rotate_to = keyring["rotated"]
    sso.token_response = token_response(keyring["rotated"], claims())

    response = come_back(client, begin_login(client))

    assert response.status_code == 303
    assert "sso_error" not in response.headers["location"]
    assert sso.jwks_fetches == 2, "the key set should have been fetched again"


def test_eve_is_asked_for_its_documents_once_per_server(client, sso, keyring):
    sso.token_response = token_response(keyring["primary"], claims())
    come_back(client, begin_login(client))
    sso.token_response = token_response(keyring["primary"], claims())
    come_back(client, begin_login(client))

    assert sso.metadata_fetches == 1
    assert sso.jwks_fetches == 1


def test_login_is_a_503_with_instructions_when_no_client_id_is_set(client, app_state, monkeypatch):
    monkeypatch.setattr(app_state.config, "dev_auth_bypass", False)
    monkeypatch.setattr(app_state.config, "sso", SsoConfig())

    response = client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 503
    assert "PYFA_WEB_SSO_CLIENT_ID" in response.json()["detail"]


def test_the_dev_bypass_logs_in_without_touching_the_sso(client, app_state, sso, monkeypatch):
    monkeypatch.setattr(app_state.config, "dev_auth_bypass", True)
    sso.fail = realRequests.ConnectionError("nothing should be asked of EVE")

    response = client.get("/api/auth/login", follow_redirects=False)

    assert response.status_code == 303
    assert client.get("/api/auth/me").json()["authenticated"] is True
    assert sso.calls == []


# -- the client on its own --------------------------------------------------------------


def test_the_verifier_is_kept_and_only_its_hash_is_sent(monkeypatch, keyring):
    stub = StubSso([keyring["primary"].jwk])
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(client_id="an-app"))

    verifier = "a-verifier-we-keep-to-ourselves"
    url = client.authorize_url("https://pyfa.example.com/api/auth/callback", "a-state", verifier)
    query = parse_qs(urlsplit(url).query)

    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
    assert query["code_challenge"] == [expected]
    assert "a-verifier-we-keep-to-ourselves" not in url


@pytest.mark.parametrize("client_secret,expected", [("", False), ("a-secret", True)])
def test_the_token_exchange_sends_what_it_has(monkeypatch, keyring, client_secret, expected):
    stub = StubSso([keyring["primary"].jwk])
    stub.token_response = token_response(keyring["primary"], claims())
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(client_id="an-app", client_secret=client_secret))

    client.exchange_code("the-code", "the-verifier", "https://pyfa.example.com/api/auth/callback")

    payload = stub.token_payload()
    assert payload["grant_type"] == "authorization_code"
    assert payload["code"] == "the-code"
    assert payload["code_verifier"] == "the-verifier"
    assert payload["redirect_uri"] == "https://pyfa.example.com/api/auth/callback"
    assert ("client_secret" in payload) is expected
    assert stub.headers["Host"] == "login.eveonline.com", "EVE checks the Host header here"


@pytest.mark.parametrize("issuer", [
    "https://login.eveonline.com",   # what CCP puts in the claim
    "login.eveonline.com",           # the bare host, as the desktop client allows
])
def test_both_issuer_spellings_are_accepted(monkeypatch, keyring, issuer):
    stub = StubSso([keyring["primary"].jwk])
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(server="Tranquility", client_id="an-app"))

    token = keyring["primary"].token(claims(issuer=issuer))
    assert client.validate_jwt(token)["sub"].startswith("CHARACTER:EVE:")


@pytest.mark.parametrize("issuer", [
    "https://login.evepc.163.com",   # NetEase's claim
    "login.evepc.163.com",           # and the issuer its metadata publishes
])
def test_serenity_issuers_are_accepted(monkeypatch, keyring, issuer):
    stub = StubSso([keyring["primary"].jwk], metadata=SERENITY)
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(server="Serenity", client_id="a-serenity-app"))

    token = keyring["primary"].token(claims(issuer=issuer))
    assert client.validate_jwt(token)["sub"].startswith("CHARACTER:EVE:")


def test_a_token_from_another_issuer_is_refused(monkeypatch, keyring):
    stub = StubSso([keyring["primary"].jwk])
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(client_id="an-app"))

    token = keyring["primary"].token(claims(issuer="https://evil.example.com"))
    with pytest.raises(webAuth.SsoError):
        client.validate_jwt(token)


def test_the_ec_key_in_the_key_set_does_not_get_in_the_way(monkeypatch, keyring):
    """Both live key sets publish an EC key beside the RSA one."""
    stub = StubSso([keyring["primary"].jwk, EC_KEY])
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(client_id="an-app"))

    assert client.validate_jwt(keyring["primary"].token(claims()))["name"]


def test_a_token_without_a_key_id_is_verified_against_the_rsa_key(monkeypatch, keyring):
    """Older tokens name no key, and the key set holds more than one entry."""
    stub = StubSso([EC_KEY, keyring["primary"].jwk])
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(client_id="an-app"))

    assert client.validate_jwt(keyring["primary"].token(claims(), kid=False))["name"]


def test_a_published_symmetric_key_is_never_used(monkeypatch, keyring):
    """HMAC tokens must not become acceptable just because the key set names a secret:
    an attacker could sign one themselves, and a `kid` is all it takes to be picked."""
    stub = StubSso([keyring["primary"].jwk, SYMMETRIC_KEY])
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(client_id="an-app"))

    forged = jwt.encode(claims(), "secret", algorithm="HS256",
                        headers={"kid": SYMMETRIC_KEY["kid"]})
    with pytest.raises(webAuth.SsoError):
        client.validate_jwt(forged)


def test_an_opaque_access_token_is_refused(monkeypatch, keyring):
    stub = StubSso([keyring["primary"].jwk])
    monkeypatch.setattr(webAuth, "requests", stub)
    client = SsoClient(SsoConfig(client_id="an-app"))

    with pytest.raises(webAuth.SsoError, match="JWT"):
        client.validate_jwt("not-a-jwt")


def test_an_unreachable_metadata_endpoint_is_reported_as_such(monkeypatch):
    stub = StubSso([])
    stub.fail = realRequests.ConnectionError("the network is gone")
    monkeypatch.setattr(webAuth, "requests", stub)

    with pytest.raises(webAuth.SsoError) as failure:
        SsoClient(SsoConfig(client_id="an-app")).metadata()

    assert failure.value.code == webAuth.SSO_UNREACHABLE


def test_an_unknown_server_name_explains_itself(monkeypatch, keyring):
    with pytest.raises(webAuth.SsoError, match="Unknown EVE server"):
        SsoClient(SsoConfig(server="Nemesis", client_id="an-app")).metadata()
