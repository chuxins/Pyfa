"""FastAPI application factory.

Startup order matters: pyfa's engine has to be up (and ``eve.db`` built) before
the first request, so the bootstrap runs before the app is created rather than in
a lifespan handler -- that way a broken data directory fails immediately and
loudly instead of on someone's first request.
"""

import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from logbook import Logger

from web import engine
from web.api import api, eventsApi
from web.api.auth import CALLBACK_PATH
from web.api.images import router as imagesRouter
from web.config import load_config
from web.deps import APP_STATE_KEY, AppState, UserContextMiddleware
from web.events import bus

pyfalog = Logger(__name__)

APP_VERSION = "0.1.0"

#: Methods that change state and therefore get an Origin check
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state: AppState = app.state.pyfaAppState
    bus.bind_loop(asyncio.get_running_loop())
    eviction = asyncio.create_task(_evict_idle_loop(state))
    pyfalog.info("pyfa web server ready on {}:{}", state.config.host, state.config.port)
    try:
        yield
    finally:
        eviction.cancel()
        try:
            await eviction
        except asyncio.CancelledError:
            pass
        state.close()
        pyfalog.info("pyfa web server stopped")


async def _evict_idle_loop(state: AppState, interval=300):
    """Close the databases of users who have gone away."""
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(state.registry.evict_idle)
        except Exception:
            pyfalog.exception("Idle user eviction failed")


class OriginCheckMiddleware:
    """Reject cross-site state changes.

    Session cookies are ``SameSite=Lax``, which already blocks cross-site form
    posts; this is the belt-and-braces check for anything that slips through
    (older browsers, same-site subdomains).
    """

    def __init__(self, app, state: AppState):
        self.app = app
        self.state = state
        allowed = {state.config.public_url.rstrip("/")} if state.config.public_url else set()
        allowed.update(origin.rstrip("/") for origin in state.config.cors_origins)
        self.allowed = {entry for entry in allowed if entry}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api"):
            await self.app(scope, receive, send)
            return

        origin = None
        for key, value in scope.get("headers") or ():
            if key == b"origin":
                origin = value.decode("latin-1").rstrip("/")
                break
        # Non-browser clients (curl, tests) send no Origin; nothing to compare
        if origin and origin not in self.allowed:
            host = scope.get("headers") and _host_of(scope)
            if origin != (host or ""):
                response = JSONResponse(
                    {"detail": "cross-site request rejected"}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _host_of(scope):
    for key, value in scope.get("headers") or ():
        if key == b"host":
            host = value.decode("latin-1")
            scheme = scope.get("scheme", "http")
            return "{}://{}".format(scheme, host)
    return None


def create_app(config=None):
    """Build the ASGI application (the engine is initialised as a side effect)."""
    config = config or load_config()
    engine.initialize(config)

    state = AppState(config)

    app = FastAPI(
        title="pyfa web",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    setattr(app.state, APP_STATE_KEY, state)
    # Convenience back-reference; test helpers and admin tooling use it
    state.app = app

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_middleware(OriginCheckMiddleware, state=state)
    app.add_middleware(UserContextMiddleware, state=state)

    app.include_router(api)
    app.include_router(eventsApi)
    app.include_router(imagesRouter)

    _mount_frontend(app, config)

    callback_warning = _callback_path_warning(config)
    if callback_warning:
        pyfalog.warning(callback_warning)
    return app


def _mount_frontend(app, config):
    dist = Path(config.frontend_dist)
    index = dist / "index.html"

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    async def root(request: Request):
        forwarded = _forward_callback(request)
        if forwarded is not None:
            return forwarded
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(_placeholder_page(config))

    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str):
        """Serve built assets, and hand unknown paths to the SPA router."""
        if path.startswith("api/") or path.startswith("img/") or path.startswith("docs"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = (dist / path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            return JSONResponse({"detail": "not found"}, status_code=404)
        if candidate.is_file():
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(_placeholder_page(config))


def _forward_callback(request):
    """Hand an SSO answer that arrived at the app page to the route that handles it.

    A callback URL registered without a path -- ``http://127.0.0.1:8080/``, a shape EVE
    accepts -- sends the browser to ``/``, the app itself, with ``?code=...&state=...``.
    Nothing there would exchange the code, and a login would look like it did nothing at
    all. The query string is passed on untouched, so the handler answers exactly as if
    EVE had used its own path.

    Only an OAuth answer is forwarded: ``code``, or an error with the ``state`` it belongs
    to. The app's own query parameter (``sso_error``) is not one of those and stays put.
    """
    params = request.query_params
    if "code" not in params and not ("error" in params and "state" in params):
        return None
    query = request.url.query
    # The code is deliberately left out of the log line; the access log has the path
    pyfalog.info("SSO answered on /: forwarding to {}", CALLBACK_PATH)
    return RedirectResponse(CALLBACK_PATH + ("?" + query if query else ""), status_code=303)


def _callback_path_warning(config):
    """A sentence for the log when the browser would come back to a path we do not serve.

    ``sso.callback_path`` is half of the ``redirect_uri`` sent to CCP, and CCP accepts only
    the callback URL registered on the application. Pointed anywhere else -- a typo, a path
    a reverse proxy was supposed to rewrite -- the code arrives at a path that serves the
    app, and the login fails with no explanation beyond "nothing happened".
    """
    path = config.sso.callback_path or "/"
    if path in ("/", CALLBACK_PATH):
        return None
    return (
        "SSO callback_path {!r} is not a path this server answers: redirect_uri would be "
        "{}, and only {} and / are handled. Register {}, or set sso.callback_path to the "
        "callback URL the application actually has.".format(
            path, config.callback_url(), CALLBACK_PATH, config.callback_url()
        )
    )


def _placeholder_page(config):
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>pyfa web</title>
<style>
body {{ font: 14px/1.5 system-ui, sans-serif; margin: 3rem auto; max-width: 40rem; }}
code {{ background: #f3f3f3; padding: .1rem .3rem; border-radius: 3px; }}
</style></head>
<body>
<h1>pyfa web</h1>
<p>The API is running, but the frontend has not been built yet.</p>
<pre>cd web/frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>Until then, these work:</p>
<ul>
  <li><a href="/api/docs">/api/docs</a> &mdash; interactive API documentation</li>
  <li><a href="/api/meta">/api/meta</a></li>
  <li><a href="/api/ships/tree">/api/ships/tree</a></li>
  <li><code>POST /api/auth/login</code> via <a href="/api/auth/login">/api/auth/login</a>{sso}</li>
</ul>
</body></html>""".format(sso="" if config.sso.configured or config.dev_auth_bypass else " (needs SSO credentials)")
