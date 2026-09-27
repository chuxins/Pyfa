"""Entry point: ``python -m web``.

    python -m web --host 127.0.0.1 --port 8080

Environment variables (all optional) are documented in ``web/docs/web.md``; the
important one for a first run is ``PYFA_WEB_DEV_AUTH_BYPASS=1``, which lets you
in without registered EVE SSO credentials.
"""

import argparse
import os
import sys


def _log_level(name):
    """A logbook level for one of the level names uvicorn accepts.

    logbook spells its levels in capitals where uvicorn spells them in lower case, and it
    raises for a name it does not know -- a typo in ``PYFA_WEB_LOG_LEVEL`` should not stop
    the server from starting.
    """
    import logbook

    try:
        return logbook.lookup_level((name or "").strip().upper())
    except LookupError:
        return logbook.lookup_level("INFO")


def _setup_logging(log_level):
    """Send pyfa's own log records to stderr, and return the handler.

    The desktop app does its work inside ``config.logging_setup``, which writes to a file
    in the user's data directory. A server has no such wrapper, and logbook drops every
    record while no handler is pushed: a failed login used to leave no trace in the log at
    all, and the browser could only say which kind of failure it was. Stderr is the right
    place for a server -- the console, the process manager and Docker all collect it.
    """
    import logbook

    handler = logbook.StreamHandler(sys.stderr, level=_log_level(log_level), bubble=False)
    handler.push_application()
    return handler


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="python -m web", description="Run the pyfa web front end")
    parser.add_argument("--host", help="interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port to bind (default 8080)")
    parser.add_argument("--data-dir", help="where the server keeps its databases (default ./webdata)")
    parser.add_argument("--public-url", help="base URL the browser uses, e.g. https://pyfa.example.com")
    parser.add_argument("--language", help="language for the UI and game data text, e.g. zh_CN (default en_US)")
    parser.add_argument("--reload", action="store_true", help="reload on code changes (development)")
    parser.add_argument("--dev-login", action="store_true",
                        help="log in without EVE SSO (development only; also PYFA_WEB_DEV_AUTH_BYPASS=1)")
    return parser.parse_args(argv)


def _cli_overrides(args):
    """The ``PYFA_WEB_*`` variables this command line sets.

    Command line beats the environment, which beats ``web.yml``, so the flags are
    applied as environment variables instead of after :func:`web.config.load_config`.
    Flags that were not given are left out, so they keep whatever the environment
    (or the file) says.
    """
    overrides = {
        "PYFA_WEB_HOST": args.host,
        "PYFA_WEB_PORT": None if args.port is None else str(args.port),
        "PYFA_WEB_DATA_DIR": args.data_dir,
        "PYFA_WEB_PUBLIC_URL": args.public_url,
        "PYFA_WEB_LANGUAGE": args.language,
        "PYFA_WEB_DEV_AUTH_BYPASS": "1" if args.dev_login else None,
    }
    return {name: value for name, value in overrides.items() if value is not None}


def main(argv=None):
    args = _parse_args(argv)

    for name, value in _cli_overrides(args).items():
        os.environ[name] = value

    import uvicorn

    from web.config import load_config

    config = load_config()

    # Before anything else logs: from here on, pyfa's own messages reach the console
    _setup_logging(config.log_level)

    # Imported only once the config is known: web.main pulls in eos.db, and eos binds
    # gamedata names to one of eve.db's language columns while it is being imported.
    from web.main import create_app

    app = create_app(config)

    if config.dev_auth_bypass:
        print("=" * 72)
        print("WARNING: dev login is enabled; anyone who can reach this port is")
        print("         logged in as the shared development account.")
        print("=" * 72)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=(config.log_level or "info").lower(),
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

