"""Login, logout and "who am I".

A login that fails after EVE has sent the browser back cannot show it a message: the
browser is in the middle of a redirect chain and the reason may quote a token. So the
failure is answered with a redirect into the app carrying one of the codes from
:mod:`web.auth`, which the front end renders as a sentence of its own.
"""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from logbook import Logger

from web.auth import (
    LOGIN_CANCELLED,
    LOGIN_EXPIRED,
    LOGIN_FAILED,
    SsoError,
    dev_login_claims,
    store_sso_character,
)
from web.deps import (
    AppState,
    bind_user_context,
    clear_session_cookie,
    current_user,
    get_app_state,
    set_session_cookie,
)

pyfalog = Logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

#: Only relative paths may be used as a post-login destination
MAX_NEXT_LENGTH = 512

#: Query parameter the app reads a failed login from
SSO_ERROR_PARAM = "sso_error"

#: Where the browser comes back to, as mounted below (``/api`` + ``/auth`` + ``/callback``).
#: ``sso.callback_path`` has to name this path or ``/``: an answer that arrives at the app
#: page is forwarded here (see :func:`web.main._forward_callback`), which is what makes a
#: callback URL registered without a path (``http://127.0.0.1:8080/``) work.
CALLBACK_PATH = "/api/auth/callback"


def _safe_next(value):
    """Only relative, same-origin paths may be used as a post-login destination."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    if len(value) > MAX_NEXT_LENGTH:
        return "/"
    # A backslash is a path separator to some browsers, and anything that parses
    # with a host would take the redirect off-site
    if "\\" in value or urlsplit(value).netloc:
        return "/"
    return value


def _login_failed(error):
    """Send the browser back into the app, told which kind of failure it was."""
    pyfalog.warning("SSO login failed ({}): {}", error.code, error)
    return RedirectResponse("/?{}={}".format(SSO_ERROR_PARAM, error.code), status_code=303)


@router.get("/login")
def login(
    next: str = "/",
    state: AppState = Depends(get_app_state),
):
    """Start the SSO flow, or log straight in when the dev bypass is on."""
    destination = _safe_next(next)

    if state.config.dev_auth_bypass:
        pyfalog.warning("DEV_AUTH_BYPASS is enabled: logging in without EVE SSO")
        claims = dev_login_claims()
        user = state.users.upsert_from_sso(
            character_id=claims["sub"].split(":")[-1],
            character_name=claims["name"],
        )
        response = RedirectResponse(destination, status_code=303)
        set_session_cookie(response, state, user.id)
        return response

    if not state.config.sso.configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "EVE SSO is not configured on this server. Set PYFA_WEB_SSO_CLIENT_ID "
                "(and register the callback URL with CCP), or enable PYFA_WEB_DEV_AUTH_BYPASS "
                "for local development."
            ),
        )

    ssoState, verifier = state.login_states.create(destination)
    try:
        url = state.sso.authorize_url(state.config.callback_url(), ssoState, verifier)
    except SsoError as ex:
        # EVE's endpoints are fetched from CCP on the way in, so the way *to* EVE can
        # fail too; the browser is told which kind of failure it was, like any other.
        return _login_failed(ex)
    return RedirectResponse(url, status_code=303)


@router.get("/callback")
def callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    appState: AppState = Depends(get_app_state),
):
    """EVE sends the browser here with an authorization code.

    Every parameter is optional because this is a redirect target, not a form: EVE answers
    with ``?error=access_denied&state=...`` when the pilot declines at the consent page,
    and a request that arrives without a code is not an error in the API sense -- the
    browser still needs to land somewhere that tells it what happened.
    """
    if error or not code or not state:
        # The state is left in the store rather than consumed: without a code nothing can
        # be exchanged with it, and the store drops it on its own after its timeout.
        if error == "access_denied":
            return _login_failed(SsoError("The pilot declined the login at EVE", LOGIN_CANCELLED))
        if error:
            return _login_failed(SsoError("EVE refused the login: {}".format(error), LOGIN_FAILED))
        return _login_failed(SsoError("EVE came back without an authorization code", LOGIN_EXPIRED))

    try:
        entry = appState.login_states.consume(state)
        token_response = appState.sso.exchange_code(code, entry.verifier, appState.config.callback_url())
        claims = appState.sso.validate_jwt(token_response["access_token"])
        character_id, character_name = appState.sso.character_from_claims(claims)
    except SsoError as ex:
        return _login_failed(ex)

    user = appState.users.upsert_from_sso(
        character_id=character_id,
        character_name=character_name,
        owner_hash=claims.get("owner", ""),
        scopes=" ".join(claims.get("scp") or []),
    )

    # Store the tokens in the user's own database so pyfa's ESI code can fetch
    # skills and fittings for this pilot from now on.
    try:
        with appState.registry.acquire(user.id) as data:
            store_sso_character(
                data, character_id, character_name,
                appState.config.sso.server, token_response)
    except Exception:
        pyfalog.exception(
            "Logged in {} but failed to store SSO tokens; skills/fittings import "
            "will need another login", character_name)

    response = RedirectResponse(_safe_next(entry.next_url), status_code=303)
    set_session_cookie(response, appState, user.id)
    pyfalog.info("User {} ({}) signed in", character_name, character_id)
    return response


@router.post("/logout")
def logout(state: AppState = Depends(get_app_state)):
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response, state)
    return response


@router.get("/me")
def me(request: Request, state: AppState = Depends(get_app_state)):
    user = current_user(request)
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": {
            "id": user.id,
            "characterId": user.character_id,
            "characterName": user.character_name,
            "scopes": user.scopes.split() if user.scopes else [],
            "createdAt": user.created_at.isoformat() if user.created_at else None,
            "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
        },
    }

