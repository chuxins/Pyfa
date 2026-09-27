"""Operator tooling: ``python -m web.admin``.

Accounts, sessions and per-user databases live on the server's disk, and none of
this is reachable over HTTP. That is deliberate: whoever can run this command can
already read the data directory, so there is no "admin account" to protect and no
new way in for anyone else.

    python -m web.admin list [--fits]
    python -m web.admin disable <user-id>
    python -m web.admin enable <user-id>
    python -m web.admin delete-data <user-id> [--yes]
    python -m web.admin import-db <user-id> <saveddata.db> [--force]

Stop the server first: a database it has open cannot be deleted or replaced, which
on Windows in particular means the command appears to succeed and changes nothing.
"""

import argparse
import sys
from pathlib import Path

from logbook import Logger

from web.config import load_config
from web.engine import EngineStartupError
from web.userdata import UserDataRegistry, count_fits, database_files, migrate_desktop_database
from web.userdb import UserStore

pyfalog = Logger(__name__)


class AdminError(Exception):
    """Something the operator has to fix before the command can be carried out."""


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m web.admin",
        description="Operate on the server's accounts and per-user databases")
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="show accounts")
    listing.add_argument("--fits", action="store_true",
                         help="also count each account's fits (opens every database)")

    disable = commands.add_parser("disable", help="lock an account out, keeping its fits")
    disable.add_argument("user_id", type=int, help="account id, as shown by 'list'")

    enable = commands.add_parser("enable", help="let a disabled account back in")
    enable.add_argument("user_id", type=int, help="account id, as shown by 'list'")

    delete = commands.add_parser("delete-data",
                                 help="delete an account's database and settings")
    delete.add_argument("user_id", type=int, help="account id, as shown by 'list'")
    delete.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    importer = commands.add_parser("import-db", help="adopt a desktop saveddata.db")
    importer.add_argument("user_id", type=int,
                          help="account id; the pilot must have signed in once")
    importer.add_argument("source", help="path to the desktop's saveddata.db")
    importer.add_argument("--force", action="store_true",
                          help="replace the account's existing database")
    return parser.parse_args(argv)


def list_accounts(config, with_fits=False):
    """Print every account. Returns how many databases could not be read."""
    users = UserStore(config.app_db_path).list_users()
    if not users:
        print("no accounts yet; the first sign-in creates one")
        return 0

    counts = _fit_counts(config, users) if with_fits else {}
    print("{:>6}  {:<28} {:>12} {:>6}  {}".format("id", "character", "eve id", "fits", "state"))
    for user in users:
        print("{:>6}  {:<28} {:>12} {:>6}  {}".format(
            user.id,
            user.character_name,
            user.character_id,
            "-" if not with_fits else _show_count(counts.get(user.id)),
            "disabled" if user.is_disabled else "active",
        ))
    return sum(1 for count in counts.values() if count is None)


def set_disabled(config, user_id, disabled):
    """Disable or re-enable an account."""
    store = UserStore(config.app_db_path)
    if not store.set_disabled(user_id, disabled):
        raise AdminError("no account {}".format(user_id))
    user = store.get(user_id)
    name = user.character_name if user is not None else "account"
    print("{} (account {}) is now {}".format(
        name, user_id, "disabled" if disabled else "enabled"))
    return 0


def delete_data(config, user_id, assume_yes=False):
    """Delete one account's database and settings; the account row itself stays."""
    user = UserStore(config.app_db_path).get(user_id)
    if user is None:
        raise AdminError("no account {}".format(user_id))

    if not assume_yes:
        answer = input("delete the saveddata of {} (account {})? [y/N] ".format(
            user.character_name, user_id))
        if answer.strip().lower() not in ("y", "yes"):
            print("nothing deleted")
            return 1

    registry = UserDataRegistry(config)
    try:
        registry.delete_user_data(user_id)
    finally:
        registry.close_all()
    print("deleted the database and settings of {} (account {}); "
          "the account itself was kept, so their next sign-in starts fresh".format(
              user.character_name, user_id))
    return 0


def import_db(config, user_id, source, force=False):
    """Make a desktop ``saveddata.db`` the database of one account."""
    from web import engine

    source_path = Path(source)
    if not source_path.is_file():
        raise AdminError("{} is not a file".format(source_path))
    user = UserStore(config.app_db_path).get(user_id)
    if user is None:
        raise AdminError(
            "no account {}: that pilot has to sign in once before their data can "
            "be replaced".format(user_id))

    # Up front, so a server that cannot start the engine has not already deleted
    # or overwritten a working database
    engine.initialize(config)

    target = config.user_db_path(user_id)
    if target.exists():
        if not force:
            raise AdminError(
                "account {} already has a saveddata.db; pass --force to replace "
                "it".format(user_id))
        registry = UserDataRegistry(config)
        try:
            registry.close_user(user_id)
        finally:
            registry.close_all()
        for path in database_files(config.user_dir(user_id)):
            try:
                path.unlink()
            except OSError as ex:
                raise AdminError("could not remove {}: {}".format(path, ex))

    data = migrate_desktop_database(source_path, user_id, config)
    try:
        fits = count_fits(data)
    finally:
        data.close()
    print("imported {} as the database of {} (account {}, {} fits)".format(
        source_path, user.character_name, user_id, fits))
    return 0


def _fit_counts(config, users):
    """Fit counts by user id; ``None`` for a database that could not be opened."""
    from web import engine

    engine.initialize(config)
    registry = UserDataRegistry(config)
    counts = {}
    try:
        for user in users:
            try:
                counts[user.id] = count_fits(registry.get(user.id))
            except Exception as ex:
                pyfalog.warning("Could not read the database of user {}: {}", user.id, ex)
                counts[user.id] = None
    finally:
        registry.close_all()
    return counts


def _show_count(count):
    return "?" if count is None else str(count)


def main(argv=None):
    args = _parse_args(argv)
    config = load_config()
    try:
        if args.command == "list":
            return list_accounts(config, with_fits=args.fits)
        if args.command == "disable":
            return set_disabled(config, args.user_id, True)
        if args.command == "enable":
            return set_disabled(config, args.user_id, False)
        if args.command == "delete-data":
            return delete_data(config, args.user_id, assume_yes=args.yes)
        if args.command == "import-db":
            return import_db(config, args.user_id, args.source, force=args.force)
    except (AdminError, EngineStartupError) as ex:
        print("error: {}".format(ex), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
