# pyfa web

Run pyfa's fitting engine as a web application, so several people can each keep
their own fits in the browser.

This document covers how it works, how to run it, and the decisions made when
putting it together.

## What you get

A FastAPI server that reuses pyfa's own engine and editing commands, and a Vue 3
single-page app in the browser:

* ship browser (class tree, search, fits per ship -- each ship showing how many fits it
  has, listed under it, and one button that imports the pilot's in-game fittings from EVE)
* fitting view: high/med/low/rig/subsystem racks, drones, fighters, cargo,
  implants, boosters, projected items, with a state chip on every module -- click
  walks online, active and overloaded, ctrl-click takes it offline. A module that
  takes ammunition carries a charge slot beside its name; the game data's charge
  groups decide, so a heat sink, an armor plate or a microwarpdrive has none and
  the fit never offers to load a charge into one. Clicking the charge that is in a
  slot opens that module's charge list with the round in there marked, which is how
  a different ammunition is picked
* weapon grouping in the high rack: one button links the same weapon there, and
  while it is on a state click or a loaded charge reaches every weapon in the
  group. Nothing about it is saved -- the engine has no weapon groups, so it lives
  in the browser and lasts as long as the fit stays open
* the item panel opened from a row of a fit shows what the fit makes of that item:
  post-fit values for a module, drone, fighter, cargo stack, implant, booster or the
  charge loaded in a module, each modified attribute with its base value beside it,
  and the charges that item can take -- a tab that is only there when it can take any
* the same stats the desktop window shows: firepower (with spool-up ranges),
  capacitor, tank, resistances, resources, targeting, remote reps, mining
* editing with **the desktop's own undo/redo stack** for every fit
* live updates: two tabs on the same fit stay in sync over server-sent events
* the UI chrome in English or simplified Chinese, with the language picked per
  browser, plus game data text (ship, item, group, category and attribute names, and
  the units they are measured in) in the language set for the whole server (see
  "Interface language")
* no sign-in wall: ship and item data are readable without an account, so the browser,
  the fitting view and the stats are up from the start; the clicks that have to write ask
  for a login in a dialog and come back to the same page afterwards (see "Signing in"),
  while the top bar keeps its sign-in link and its sign-out button either way
* opening the app lands on the fit that was last worked on, so the assembly page is what
  comes up rather than an empty frame; the id is remembered in the browser alone, and a
  first visit opens the most recently changed fit

## Running it

```bash
# 1. dependencies (Python 3.12+; wxPython is *not* needed for the server)
uv sync --group web --no-group wx-source --no-group wx-binary   # or: pip install -e .[web]

# 2. build the frontend once (needs Node 20+)
cd web/frontend && npm install && npm run build && cd ../..

# 3. start the server
PYFA_WEB_DEV_AUTH_BYPASS=1 python -m web --port 8080
# then open http://127.0.0.1:8080
```

`EVE static data` (`eve.db`, ~100 MB) is built automatically on first start from
the `staticdata/` directory that ships with pyfa. If `eve.db` is missing and
`staticdata/` is absent too, startup fails with a clear message.

### Development

Two processes, with the Vite dev server proxying to the API:

```bash
python -m web --dev-login          # terminal 1: API on :8080
cd web/frontend && npm run dev     # terminal 2: UI on :5173
```

### Interface language

The language has two halves: the UI chrome, which a browser can switch on its own,
and the game data text (ship, module and attribute names), which is the same for
everyone. `--language` (or `PYFA_WEB_LANGUAGE`, or `language:` in `web.yml`) sets
both:

```bash
python -m web --language zh_CN
```

The UI chrome ships English and simplified Chinese (`web/frontend/src/i18n.ts`);
the picker in the top bar switches one browser's chrome and remembers the choice.
The browser resolves the language in this order: the picker's stored choice, then
the language the server reports in `/api/meta`, then the browser's own language,
then English. Starting from the server's language is deliberate -- it is also the
language of the game data the panes are showing, so a `zh_CN` server gives a
Chinese ship browser and Chinese item names to a browser that has never been
configured.

Game data text comes from `eve.db`, which stores translated names in per-language
columns. pyfa has columns for English, French, Japanese, Korean, Russian and
Chinese, so `fr_FR`, `ja_JP`, `ko_KR`, `ru_RU` and `zh_CN` translate item names,
group and category names, and search; any other language gives English names (the
same fall-back the desktop client uses). Unknown names fall back per row, so a mix
of languages in the tree only means that item has no translation in that column.

Attribute names and their units are read from those columns too, which is why the item
panel is in the server's language as well. A *fitted* item is the case worth naming:
its values come from the fitting engine, while its names still come from the game data,
so the panel would otherwise switch language the moment a fit was involved (see
`display_name` in `web/services/serialize.py`). Attributes the game data has no name
for -- the unpublished ones, which the desktop's item window hides in its normal view
too -- are left out rather than shown by their internal name.

eos binds an item's name to one of those columns *when it first imports the
gamedata models*, so this is decided once at startup and cannot be per user:
`load_config` hands the language to eos before `web.main` is imported, and
`web.engine.apply_gamedata_language` runs again while the engine boots. Restart
the server to change it.

What no setting translates is text the engine generates, such as the undo/redo
tooltips. pyfa's own catalogue covers those (including a complete `zh_CN`), but it is
loaded from compiled `.mo` files, which are build artifacts here (`*.mo` is
gitignored) and are not part of this checkout. A *rejected edit* is not in that
group: the server answers with a code, not only a sentence, and the browser writes
the sentence itself (see "Refused edits"). Everything written by the front end itself
-- including the tooltips, banners and empty states in the panels -- is translated.

## Signing in

EVE SSO is the only login method: a user *is* an EVE character, which is also how
their fits stay tied to the pilot that owns them.

Signing in is not a gate in front of the page. Reads work without a session -- a request
with no user is answered from a guest context, which is why the ship tree, the item
browser and the stats panes draw for a visitor -- so what a session adds is the fits
themselves, the live updates and every write. A click that writes (importing the in-game
fittings, a new fit, fitting a module) therefore asks for the login at that point, in a
dialog whose button comes back to the same page (`?next=`), rather than failing with an
error the click cannot act on. Every `401` is reported to the shell (`onUnauthorized` in
`web/frontend/src/api.ts`) and raises the same dialog
(`web/frontend/src/components/LoginPrompt.vue`), so no write has to recognise it on its
own. The top bar keeps a plain sign-in link while nobody is signed in and a sign-out
button with the character name while somebody is.

You must register an application with CCP (<https://developers.eveonline.com>)
whose **callback URL** is exactly `PYFA_WEB_PUBLIC_URL` + `sso.callback_path` --
`https://pyfa.example.com/api/auth/callback` with the default path, or a bare
origin such as `http://127.0.0.1:8080/` if that is what the portal has on it.
Requesting the scopes pyfa needs:

```
esi-skills.read_skills.v1 esi-fittings.read_fittings.v1 esi-fittings.write_fittings.v1
```

Then provide the credentials:

```bash
export PYFA_WEB_SSO_CLIENT_ID=your_client_id
export PYFA_WEB_SSO_CLIENT_SECRET=your_secret    # optional; see below
export PYFA_WEB_PUBLIC_URL=https://pyfa.example.com
```

The flow is authorization code + PKCE with a single-use `state`; the tokens are
verified against the SSO's JWKS before the account row is created. pyfa's own
`SsoCharacter` record (with the encrypted refresh token) is written into that
user's database, so the existing ESI code for skills and fitting import has what it
needs -- see "Importing the fits saved in game".

The callback URL has to match the registered one exactly, scheme and port included:
CCP compares the `redirect_uri` the browser sends with the one on the application, and
that value is `PYFA_WEB_PUBLIC_URL` + `sso.callback_path`. Unset, `public_url` falls
back to `http://<host>:<port>`, so a deployment that is reachable from the outside needs
it set to the address the browser actually uses. `callback_path` has to be a path this
server answers -- `/api/auth/callback`, or `/` for a registration that stops at the
origin -- and anything else is reported at startup instead of failing after a login.

A callback URL belongs to one application at a time: whichever process answers on that
host, port and path receives the code, and a session only exists in the process that did
the exchange. A `public_url` without an explicit port (`http://8.138.203.48`) therefore
means *this* server has to own port 80 -- the container is published as `80:8080` in
`compose.yml` -- because the browser is sent to host port 80 and nowhere else. If
something already answers there (a reverse proxy, another EVE application), give pyfa web
a callback URL of its own: a different port, or a path prefix such as
`/pyfa/api/auth/callback`. Register *that* in the developer portal and set `public_url`
to the matching base; an application cannot be signed into through two different servers
sharing one callback URL.

A working copy registered as `http://127.0.0.1:8080/` runs as itself, with nothing set in
the environment: `web.yml` (gitignored) holds the client id and the secret, and

```bash
python -m web        # 127.0.0.1:8080, live SSO, no dev bypass
```

is the whole of it.

There is no way to see a wrong pair *before* a login succeeds. The authorize endpoint
answers `302` into `https://login.eveonline.com/account/logon?ReturnUrl=...` for *any*
client id and *any* `redirect_uri`, registered or not -- a fabricated client id and
`https://example.invalid/nope` both get exactly that `302` (measured) -- so probing it
separates nothing. CCP's documentation is where the rule is: the `redirect_uri` must be
"the full callback URL you defined for your application", and "if you put in any other
URL ... the EVE SSO will reject your request". That rejection reaches the browser *after*
the account and the scopes have been chosen, not curl before them.

What can be read off without a browser is what this server is about to send:

```bash
curl -s -o /dev/null -w '%{redirect_url}\n' http://127.0.0.1:8080/api/auth/login
python -c "from web.config import load_config; print(load_config().callback_url())"
```

Compare the `redirect_uri` in that authorize URL with the application's Callback URL
field, character for character: port and trailing slash included. A `callback_path` this
server does not answer is refused at startup instead, and the message names both the URL
it would have sent and the paths it does answer.

A registered callback without a path sends the browser to `/`, the app page, with
`?code=...&state=...` -- and the app page is not where the exchange happens. That answer
is therefore forwarded to `/api/auth/callback` with its query string intact, which is why
`sso.callback_path: /` works rather than looking like a login that silently did nothing.
Only an OAuth answer is forwarded (a `code`, or an `error` with its `state`); anything
else, an unknown path or the app's own `sso_error`, is still just the app page.

The key set is fetched once per server and fetched again when a token names a signing
key that is not in it, so a key rotation by CCP does not lock anyone out until the next
restart.

### 国服 (Serenity)

`PYFA_WEB_SSO_SERVER=Serenity` signs in through NetEase's SSO (`login.evepc.163.com`)
instead. Its endpoints come from its own metadata document, and its `iss` claim has no
scheme where CCP's is an `https://` URL; both spellings are accepted. The application has
to be registered on the Chinese side, so a CCP client id does not work there.

### When a login fails

A login that fails after EVE has sent the browser back is not answered with a JSON error
page: `/api/auth/callback` redirects into the app with `?sso_error=<code>`, and the front
end (`web/frontend/src/errors.ts`) writes the sentence in the reader's language.

| Code | What happened |
| --- | --- |
| `loginExpired` | the `state` came back unknown, already used, older than 15 minutes, or the callback carried no code |
| `loginCancelled` | the pilot declined at EVE's consent page (`error=access_denied`) |
| `ssoUnreachable` | EVE's metadata, key set, or token endpoint did not answer |
| `loginFailed` | EVE rejected the code exchange, reported an error of its own, or the token was not a valid character token |

The reason itself goes to the server log and nowhere else: EVE's answer to a failed
exchange can quote a token. pyfa's own log records reach stderr because `python -m web`
pushes a `logbook` handler at startup (`web/__main__.py`); without one, logbook discards
every record, so a failed login would leave no trace anywhere:

    WARNING: web.api.auth: SSO login failed (loginExpired): Login state is unknown or expired. Start the login again.

`PYFA_WEB_LOG_LEVEL=debug` adds the full detail of a failed exchange.

The callback takes every parameter as optional for the same reason: it is a redirect
target, and a pilot who cancels at EVE arrives with an error and no code. That used to be
an API 422 with a JSON body in the middle of a redirect chain.

A browser that arrives at the callback with a perfectly good code and still ends up
anonymous is usually talking to the wrong server. Ask the public URL what it is:
`/api/meta` on pyfa web answers `200` with `{"pyfaVersion": ...}`, `/api/openapi.json`
says `"title": "pyfa web"`, and the bare callback redirects with
`303 -> /?sso_error=loginExpired` instead of rendering anything. Another application's
HTML, JSON or "missing code" page at that address means the code was delivered elsewhere
and this server never saw it.

> **Development without credentials.** `PYFA_WEB_DEV_AUTH_BYPASS=1` (or
> `python -m web --dev-login`) logs everyone in as one shared local account. It
> exists so the app can be developed and tested without a registered SSO
> application. Never enable it on a reachable deployment: anyone who can reach
> the port becomes that account.

### Importing the fits saved in game

`POST /api/esi/fittings/import` reads `GET /characters/{id}/fittings/` from ESI with the
tokens the login stored, and turns each fitting into a fit of the caller's own database,
under the ship it belongs to. The ship browser's **Import my EVE fits** button is that
endpoint; ships that have fits show the count, and the fits are listed under the ship in
the tree.

It is one-way. Nothing is written back to EVE: renaming or deleting the copy in pyfa
leaves the in-game fitting alone, and `esi-fittings.write_fittings.v1` is not used by this
path.

* A fitting is skipped when the pilot already has a fit with the same name on the same
  ship, matched one for one -- so pressing the button twice does not double everything,
  while a second copy in EVE is still imported.
* A fitting for a hull this game data does not know is reported and skipped; the rest of
  the batch still imports.
* Every imported fit is recalculated, so the stats pane has real numbers for it.
* Drones arrive in the drone bay and *inactive*, charges and ammo in the cargo: that is
  what ESI reports (EVE does not say which crystal is loaded into which gun) and what the
  desktop's own ESI import does with the same data.

A failure at EVE's end is answered as a gateway error with a code the browser writes a
sentence for (`web/frontend/src/errors.ts`); two of them mean signing in again is what
fixes it:

| Code | What happened |
| --- | --- |
| `noCharacter` | the account has no stored tokens for the configured server |
| `tokenRefused` | EVE no longer accepts the stored tokens |
| `esiUnreachable` | ESI did not answer |
| `esiRefused` | EVE answered, refusing (403, a bad gateway, ...) |
| `esiUnusable` | EVE answered with something that is not a list of fittings |

Reading EVE's fittings turned up an old mismatch in pyfa's own importer, fixed here: ESI
*names* the item flags (`HiSlot0`, `DroneBay`, `Cargo`) where pyfa's export format uses
EVE's inventory flag ids, and `service/port/esi.py` only understood the ids -- so a
fitting imported from ESI arrived without its drones and cargo. `_flagId()` now accepts
both spellings, which the desktop's "Browse EVE Fittings" window benefits from too.

## Configuration

`web.yml` in the repository root, or environment variables prefixed
`PYFA_WEB_` (environment wins). See `web.yml.example`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PYFA_WEB_DATA_DIR` | `./webdata` | databases, settings and logs |
| `PYFA_WEB_HOST` | `127.0.0.1` | bind address |
| `PYFA_WEB_PORT` | `8080` | bind port |
| `PYFA_WEB_PUBLIC_URL` | derived | base URL the browser uses; needed for SSO |
| `PYFA_WEB_SECRET_KEY` | generated | session cookie signing key (persisted to `session.key`) |
| `PYFA_WEB_COOKIE_SECURE` | inferred | mark the cookie `Secure`; unset means infer it from `public_url` |
| `PYFA_WEB_SESSION_MAX_AGE` | `2592000` | session lifetime in seconds |
| `PYFA_WEB_LANGUAGE` | `en_US` | language for the UI and game data text (server-wide; see "Interface language") |
| `PYFA_WEB_LOG_LEVEL` | `info` | uvicorn and pyfa log level |
| `PYFA_WEB_DEV_AUTH_BYPASS` | off | development login, see above |
| `PYFA_WEB_SSO_CLIENT_ID` | – | EVE application client id |
| `PYFA_WEB_SSO_CLIENT_SECRET` | – | optional; only for confidential applications |
| `PYFA_WEB_SSO_SERVER` | `Tranquility` | `Tranquility` or `Serenity` |
| `PYFA_WEB_CORS_ORIGINS` | – | comma separated, only needed for a separate UI origin |

Every setting may come from either place, and the environment variable wins over
the same key in `web.yml`, so a deployment can override a checked-in file.
`cookie_name` is the one field with no environment variable.

## How it is put together

```
browser (Vue 3 SPA)
   │  JSON + SSE
   ▼
FastAPI  ── web/api/*      endpoints
         ── web/deps.py    session cookie → account → engine context
         ── web/userdata.py one SQLite file + session + lock per user
         ── web/admin.py   accounts and data files, from a terminal
   │
   ▼
service/*  and  eos/*      pyfa's own code, unchanged
                     └─ gui/fitCommands/calc|gui/*   pyfa's own undoable commands
```

### Reusing the desktop application

The engine was already GUI-free; the service layer only touched wx for
translations, thread marshalling and the undo stack. `pyfa_compat` supplies those
outside a GUI:

| What | How |
| --- | --- |
| `wx.GetTranslation`, `wx.Colour`, `wx.Locale` | `pyfa_compat/wx_headless.py`, including a gettext-backed translator |
| `wx.CallAfter` / `wx.PostEvent` | routed to `web/events.py`: a dispatcher thread that runs callbacks *with their original context*, and an SSE bus |
| `wx.Command` / `wx.CommandProcessor` | a faithful in-process undo stack |
| `gui.mainFrame.MainFrame.getInstance()` | `pyfa_compat/mainframe_stub.py` -- the fit commands only use it as an event target |

The headless `wx` is installed only when wxPython is missing or `web` is
imported, so a machine that also has the desktop application is unaffected.
GUI-only APIs raise `HeadlessUnsupportedError` rather than quietly doing nothing.

Because of the stub, **every edit the web UI makes runs one of pyfa's own
`Gui*Command` classes** -- the same object the desktop submits when you drag a
module into a slot. Undo, "fill with similar modules", mutation handling, charge
swapping and state cycling all behave identically as a result, and there is no
second implementation to keep in sync. `web/services/commands.py` maps JSON
command names onto those classes through an allow-list; clients never name a
Python class.

Taking several modules at once works the same way: those commands have always taken
a list of positions, because the desktop needs one for a multi-selection. The high
rack's **group weapons** button is a second user of that form. It is the browser's
own idea (`web/frontend/src/stores/fitting.ts`, `highWeaponGroups`): the engine never
hears about a weapon group, it is only ever asked to change a main module and the
positions that should follow it, so grouping costs no engine change, no database
column, and no export. What decides which modules a group can hold is the
`hardpoint` field `web/services/serialize.py` puts on every fitted weapon -- a turret,
a launcher or nothing, straight from `Module.hardpoint`.

### Refused edits

The engine is the only thing that decides whether something fits. When it says no,
`web/services/commands.py` asks the fit the same questions the command asked and
answers with the reason -- "that is ammunition, not a module", "there is no free high
slot" -- instead of a shrug. The answer is a `409` whose `detail` is
`{message, code, params}`: an English sentence for the log and for any client that
ignores codes, plus the code and the values that belong in that sentence. The browser
keeps one sentence per code in `web/frontend/src/errors.ts`, so it writes it in the
reader's language with the item name the server already translated. The two lists are
short and are meant to be read together.

An item id that is not in the game data is answered the same way rather than crashing
the engine, which is what used to happen: every command dereferences its item while it
is being built.

A state click the module cannot follow -- the chip of a passive module, which has no
state above online -- is answered with `stateUnchanged` and the state the module is
already in. The engine reports "nothing changed" the same way it reports a refusal, so
without that the browser would show "the item may not fit" for a click that merely
reached the end of the ladder.

### Per-user isolation

Each account gets `<data dir>/users/<id>/saveddata.db` -- byte-for-byte the
database the desktop uses, so a user can copy their desktop `saveddata.db` in and
find their fittings. Accounts and sessions live in a small `app.db`.

Sharing the engine between users needed four changes, all in shared code:

1. **Session resolution** (`eos/db/sessionctx.py`). `eos.db.saveddata_session` is
   now a proxy that resolves to the current user's session through a
   `contextvars` variable, falling back to the process-wide default (desktop
   behaviour) when nothing is bound. The ~130 existing call sites are untouched.
   With no user bound it raises a clear error instead of writing to the wrong
   database -- which is what stops a stray background thread from corrupting data.
   `sd_lock` is resolved the same way, so writes serialise per user rather than
   globally.
2. **Service singletons** (`service/fit.py`, `service/character.py`). `Fit` and
   `Character` cache ORM objects that belong to one user's database, so they are
   instantiated per session context instead of per process.
3. **Settings** (`service/settings.py`). The settings singletons grab their file
   once at import; in web mode they are handed a `ScopedSettings` view that
   resolves the requesting user's file on every access.
4. **Query caches off** (`web/__init__.py`). pyfa's saveddata query cache is keyed
   by fit id alone, so `getFit(1)` would serve one user's fit to another. Both
   caches are disabled for the server, and the game-data cache cannot key on the
   list arguments the search passes anyway.

Requests for the same user are serialised on an `asyncio` lock; different users
run fully in parallel. Idle user databases are closed after 30 minutes.

### Things that had to change in place

* `eos/db/__init__.py` -- session proxy, request-scoped game-data sessions
* `eos/db/migration.py` -- migrations can target a per-user database
* `eos/db/sessionctx.py` -- new
* `config.py` is unchanged; the wx shim covers it
* `service/{fit,character,settings,esi}.py` -- the changes above, plus lazy GUI
  imports in `esi.py` so character import can be used headlessly
* `gui/fitCommands/__init__.py` -- the `Gui*` commands are now resolved lazily.
  Desktop callers (`import gui.fitCommands as cmd; cmd.GuiAddLocalModuleCommand`)
  are unaffected; the point is that importing that package no longer drags the
  wxPython widget tree in, which is what lets the web server use it
* `eos/saveddata/module.py` -- `Module.getProposedState()` accepts one more click,
  ``'cycle'``, which walks a module online, active, overheated and back to online. The
  browser's state chip sends it, because a desktop click cannot reach the overloaded
  state at all: left toggles online and active, right overloads, ctrl offlines. Every
  existing click keeps its meaning, and a module with nowhere to go (passive, activation
  blocked, not overloadable) still walks pyfa's own two states.

`gui/` is otherwise untouched and the desktop application still runs.

### Efficiency notes

* Game-data reads use one session per request. pyfa's per-thread sessions would
  otherwise leak one read-only connection per worker thread until the pool
  exhausted.
* Ship icons come from `/img/renders/<graphicID>`, item icons from
  `/img/icons/<iconID>`, straight off disk with immutable cache headers. Ships
  have no `iconID` in the static data -- their picture is the render.

## Tests

```bash
python -m pytest web/tests -q
```

163 tests covering the API, the engine numbers (a Rifter with a 200mm AutoCannon II
and EMP S must show 38.96 DPS, exactly as the desktop does), the edit commands, what a
refused edit explains, the state chip's click cycle (overload included, and the passive
module the engine answers with "already online"), what the item panel reads for every
row of a fit (the charge in a module is not the module, the names come from the game
data's language columns, and an attribute the game data does not name is left out),
whether a row takes a charge at all (the flag the fitting view draws its charge slot
from: a weapon says yes, a damage control says no, and an empty slot saying nothing),
what a grouped weapon reaches (state and charge, and the weapon of another type it must
leave alone), and the undo stack. The isolation tests create two accounts and assert
that neither can see, open, or undo the other's fits, and that touching saveddata
without a bound context fails loudly. Configuration precedence (including the
`python -m web` flags), the game data language, the post-login redirect target, the
`wx.CallAfter` context and every `python -m web.admin` command are covered too, as is
the ESI fittings import: both flag spellings, a fitting already in pyfa, a hull the game
data does not have, EVE refusing or not answering, and one account trying to import
with another account's tokens.

## Administration

Accounts and per-user databases are files on the server's disk, so there is no
admin HTTP API: nothing behind a login can reach them. `python -m web.admin` is the
operator's side of that, run on the server host with the server stopped (a
database the server has open cannot be replaced or deleted).

```bash
python -m web.admin list --fits                  # who is here, and how much data
python -m web.admin disable 3                    # lock an account out, keep its fits
python -m web.admin enable 3
python -m web.admin delete-data 3 --yes          # database and settings, not the account
python -m web.admin import-db 3 ~/saveddata.db   # adopt a desktop database
```

`disable` is checked on every request, so it takes effect immediately and leaves the
fits alone. `delete-data` keeps the account row, so the pilot can sign in again and
start fresh. `import-db` needs the account to exist already (the pilot signs in
once), refuses to replace a database without `--force`, and copies the file in
rather than moving it.

## Deployment

Single machine, SQLite in WAL mode. `Dockerfile` and `compose.yml` are in this
directory:

```bash
docker compose up --build            # http://localhost:8080
```

Put it behind a TLS-terminating reverse proxy and set `PYFA_WEB_PUBLIC_URL` to the
public https URL -- the session cookie is marked `Secure` automatically in that
case. State lives in the `/data` volume (`app.db`, one `saveddata.db` per user,
server settings, logs).

The two files that describe one particular machine are gitignored. `web.yml` is
mounted read-only into the container and holds the server configuration, the SSO
credentials among it (`web.yml.example` is the template, and compose refuses to
start without the file rather than running on defaults). `.env` is read by compose
itself and carries what has to agree with the world outside the container -- the
host port and the public URL:

```
PYFA_WEB_PUBLISH=80
PYFA_WEB_PUBLIC_URL=http://8.138.203.48
PYFA_WEB_SSO_CALLBACK_PATH=/api/auth/callback
```

`callback_path` is in there because the `web.yml` a working copy keeps for itself names
its own registration (`/`, for a callback URL that stops at the origin), and an
environment variable always wins over the file. Its value here has to be the path the
deployment's application has on it.

The pair above `callback_path` is not cosmetic. A registered callback of
`http://8.138.203.48/api/auth/callback` carries no port, so the browser returns to
host port 80 and the container has to be the thing answering there (`80:8080`;
`PYFA_WEB_PUBLISH` is only read by compose, never by the app). Over plain http the
session cookie is deliberately not marked `Secure` -- the correct pairing, since a
`Secure` cookie is never sent back over http and the login would loop -- and the
authorization code travels in clear text, which makes a TLS terminator worth having
before this is more than a stopgap.

That makes the deployment, once the host and callback URL are settled:

```bash
sudo ss -ltnp 'sport = :80'          # must be empty: whoever holds 80 receives the code
docker compose up -d --build         # compose.yml + .env + web.yml; publishes 80:8080
curl -s http://8.138.203.48/api/meta # {"pyfaVersion": ...} means the right app answers
docker compose logs -f pyfa-web      # the reason for a failed login ends up here
```

Then sign in from a browser. Consent comes back to host port 80 and the browser is left
on the app page with a session; a failure comes back with `?sso_error=<code>`, which the
front page shows as a sentence for a few seconds, and the log keeps the reason behind it.

Sizing: the engine is CPU-bound per fit edit. A handful of concurrent users is
comfortable on two cores; the expensive parts are the first request after startup
(game data is read from disk) and price/market refreshes.

## Limitations, honestly

* **Item names are in one language per server** (`PYFA_WEB_LANGUAGE`, `--language`
  or `language:` in `web.yml`, and changing it needs a restart). eos binds an item's
  `name` to a language column of `eve.db` while importing the gamedata models, so
  per-user item names would need changes in `eos/db/gamedata/*`. The UI chrome *is*
  translated, but the two are independent: a browser can read the chrome in Chinese
  while the server hands out English item names.
* **Undo/redo tooltips stay in English.** They are pyfa strings translated through
  gettext, which needs compiled `.mo` catalogs; `*.mo` is a build artifact and this
  repository ships only the `.po` sources (all languages, `zh_CN` included). Compiling
  them and pointing `pyfa_compat.wx_headless.configure_i18n` at the result is what it
  would take. A refused edit is already translated: the server sends a code rather
  than only a sentence.
* **A desktop log file would be nicer than stderr** (fixed the important half of this).
  pyfa's desktop runs inside `config.logging_setup`, which writes a rotating file into the
  user's data directory; the server had no handler pushed at all, and `logbook` drops every
  record in that state (verified: even a bare `Logger(...).warning(...)` prints nothing),
  so nothing the engine or the API logged was kept. `python -m web` now pushes a stderr
  handler at startup, which is where a container or systemd unit collects it, but there is
  still no rotating file of the server's own.
* **No market browser or price display yet.** The engine side is straightforward
  (`service/price.py`), but the price cache is global while pyfa stores price rows
  per user, so it needs a decision about where that cache lives before it is
  wired up. This is the largest piece of the desktop still missing.
* **Import/export** (EFT/DNA/XML/ESI fittings, clipboard, HTML export) is not
  exposed yet; `service/port/*` is reusable for it.
* **Graphs** (capacitor simulation, DPS over range, ...) are not implemented. The
  data modules in `graphs/data/*` are GUI-free and are the intended source; the
  plan is to serialise their series and draw them client-side.
* **Right-click menus have no direct equivalent.** Everything they do is reachable
  through the UI, but a few desktop conveniences (variation pickers inline,
  "optimise fit price") are not surfaced yet.
* **Session handling is a signed cookie**, so there is no server-side revocation:
  signing out clears the cookie, but a stolen cookie stays valid until it expires
  (`PYFA_WEB_SESSION_MAX_AGE`). Rotating `PYFA_WEB_SECRET_KEY` invalidates them
  all.
* The first request after a restart is slow while `eve.db` is opened and warm.
