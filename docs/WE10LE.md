# Experimental Korean PS2 WE10 Liveware Evolution service

This service targets **Winning Eleven 10 Liveware Evolution, Korean PS2 release
SLKA-25153**. It adds a separate application and protocol adapter while reusing
the existing PES6 account, lobby, room and match models. The original Fiveserver
and Sixserver entry points remain available.

The user has confirmed gameplay between two separate PCs, in addition to
login, profile selection, lobbies and rooms with PCSX2. This is user-reported
validation, not a directly observed automated gameplay test. Final database
statistics and Docker-engine execution remain unverified. Container image
archive checks do not establish those outcomes, and one working setup does not
validate every UDP/NAT environment.

The repository contains server source, configuration, a registration form and
tests. It contains no ISO, BIOS, game executable, PNACH, memory-card image or
roster data. Passing the game's DNAS step is an external client prerequisite;
this service does not implement DNAS authentication or distribute a bypass.

## Service and configuration

Use a dedicated database initialized with [sql/schema6.sql](../sql/schema6.sql)
and a database account with the permissions described in the main README.
No new schema migration is required. Do not point this experimental service at
an existing PC service's account database without deliberately reviewing that
choice: the PS2 account credential and roster-check behavior differs.

Edit [etc/conf/we10le.yaml](../etc/conf/we10le.yaml):

- Set `ServerIP` to the IPv4 address the clients can reach. The shipped
  `127.0.0.1` is a configuration placeholder, not a remote client's destination.
- Set the `DB` connection details and keep them out of source control.
- Choose `ListenOn` for the desired local interface; an empty value binds all
  local interfaces.
- Keep PC roster checksum enforcement/comparison disabled. This PS2 client
  does not supply that checksum. `StoreSettings` remains disabled by default.

| Endpoint | Default TCP port |
| --- | --- |
| Gateway, `gate.we10le.konami-asia.com` | 10881 |
| Main service | 20210 |
| Network menu | 20211 |
| Login service | 20212 |
| Account registration HTTP | 8195 |

The game fixes the gateway port at 10881. Sixserver also uses that port, so the
two services cannot share the same listening IP/port. The gateway advertises
the configured login/menu/main endpoints; make those reachable as well.
Limit the registration web interface's exposure separately from game ports.

From the repository root, with Python 3.12 and the MySQL client build
dependencies described in the main README:

```sh
python3 -m venv .local
.local/bin/python -m pip install -r pip.requirements-we10le
./service.sh we10le run
```

On Windows, create `.local` with `py -3.12 -m venv .local`, install the same
requirements with `.local\Scripts\python.exe`, then run `./run-we10le.ps1`.
Its `-Venv` option selects another environment. `WE10LE_CONFIG` can select an
alternative YAML path for `tac/we10le.tac`; otherwise the shipped YAML is used.

## Authentication policy and registration

**The default `AuthMode: username` checks a registered account ID but does not
verify its password.** Anyone who knows a registered ID can attempt to use that
account. Unknown IDs, mismatched account identities and duplicate online
sessions are still rejected; existing stored credentials and profiles are
preserved. This mode is limited to the dedicated WE10LE services and does not
change PC authentication.

Set `AuthMode: password` to require the game's ID/password check. In the
container, `WE10LE_AUTH_MODE=username|password` overrides this setting. Login,
network-menu and main connections use the same policy.

Register through `http://<server>:8195/` using the PS2-specific form. It derives
the credential from `MD5(username + 16 NUL bytes + password)` rather than the PC
serial-based expression. This is compatibility with the game's existing
challenge/digest protocol, not a new authentication design. The form documents
the game's A–L pad-password alphabet; the game enters these characters through
controller buttons and completes input with Start. In username mode the client
still requires a nonempty password field, although the server ignores its
digest. The original PC registration form remains the default for PC services.

## Client networking prerequisites

Direct `gate.we10le.konami-asia.com` to the same reachable IPv4 used by
`ServerIP`, using client-side or local DNS. This does not require changing a
hostname inside the ISO. The [Korean setup notes](WE10LE-KR.md) describe the
PCSX2 2.8.2 internal-DNS configuration used during investigation.

The client separately uses `we9stun.winning-eleven.net` over UDP 3478 with
legacy STUN behavior. This application adds neither a UDP STUN server nor a
gameplay relay. Do not map the STUN hostname to this server merely because
the game gateway points here. Historical STUN probes in the Korean notes are
dated observations, not a guarantee that an external endpoint is available or
compatible with every NAT environment. Same-host emulator tests do not
establish connectivity between different PCs.

## Protocol implementation and shared changes

[lib/fiveserver/protocol/we10le.py](../lib/fiveserver/protocol/we10le.py)
contains the PS2 differences: authentication `3F01/3F02`, profile record widths,
profile-selection response layout, fixed-width lobby/chat responses, logout
acknowledgment and heartbeat checksum handling. Login, menu and main handlers
inherit the existing PES6 behavior rather than introducing parallel room and
match state machines. Default request/status acknowledgments are preserved.

The small shared PES5/PES6 changes correct Python 3 room-name membership and
settings-fragment classification, stop room-join processing after an error,
encode the match-time byte as an integer, and report room zero to a leaving
player. Regression tests exercise both PES6 and WE10LE where those paths are
shared. The configurable registration form and username lookup preserve the
existing PC defaults and profile hydration.

The optional community season extension uses `4F10/4F11`, version 3, only on
the Korean main service. It becomes relevant when a modified client sends a
declaration; ordinary clients need no season negotiation. It compares opaque
client-declared identities and exchanges base-team/season choices, with a
two-participant final-confirmation barrier and recipient nonce. It does not
provide roster contents or attest client RAM. Legacy-only rooms keep their
shared behavior, including the existing four-player path; mixed or mismatched
season participants cannot start a season match. See the
[protocol contract](WE10LE-SEASON-PROTOCOL.md) for the exact wire format,
lifecycle and client-side validation requirements.

The v3 server behavior is covered by automated tests. The user's two-PC
gameplay report did not identify a particular v3 client build or season roster,
so it is not an end-to-end validation of this optional extension.

## Container entry point

The dedicated [Dockerfile](../docker/we10le/Dockerfile) is separate from the
existing PC-service Dockerfile:

```sh
docker build -f docker/we10le/Dockerfile -t we10le-server:latest .
```

The image uses Python 3.12 and the PyMySQL `MySQLdb` compatibility layer, runs
as UID/GID 3066 and writes its runtime configuration privately. Supply a
separately initialized MySQL/MariaDB service reachable from the container:

| Environment variable | Purpose/default |
| --- | --- |
| `WE10LE_SERVER_IP` | Required reachable advertised IPv4 |
| `DB_PASSWORD` | Required database password |
| `DB_HOST`, `DB_PORT` | Database endpoint; defaults `db`, `3306` |
| `DB_NAME`, `DB_USER` | Defaults `we10le`, `we10le` |
| `WE10LE_AUTH_MODE` | Optional `username` or `password` override |
| `WE10LE_PROTOCOL_TRACE` | Optional `0` or `1` diagnostic override |

Attach the container to a network that can reach `DB_HOST`, publish the needed
game TCP ports, and persist `/var/lib/we10le` for the banned list. For local-only
registration access, a Docker publish option such as
`-p 127.0.0.1:8195:8195` must be selected explicitly; the Dockerfile itself does
not impose that host binding. The entry point waits for the existing `users`
and `profiles` tables; it does not create the database or initialize its schema.
There is no Compose stack, prebuilt image tar or client patch bundle in this PR.

## Testing and diagnosis

```sh
.local/bin/python -m pip install pytest
PYTHONPATH=lib .local/bin/python -m pytest tests -q
node tests/test_we10le_form.js
```

The Python suite exercises real packet framing/encryption, Twisted transports,
Deferreds and server models, with database/time boundaries replaced by test
fixtures. It covers authentication, profile hydration, registration, lobby/room
flows, shared regressions, container configuration and season negotiation.
The Node test checks the registration form's pad mapping and credential
calculation. The user's separate two-PC gameplay confirmation complements
these tests; the tests themselves do not validate the live database deployment.

Use `TraceProtocol: true` or `WE10LE_PROTOCOL_TRACE=1` for service, packet ID,
length and authentication-outcome diagnostics without raw authentication
payloads. Keep `Debug: false` when collecting this trace; the inherited raw
debug formatter is a separate diagnostic path. Unknown optional fields,
Korean text handling, less-observed network-menu features and final database
statistics still need further validation. Historical packet
evidence is in [WE10LE-KR.md](WE10LE-KR.md); shared-flow review is in
[WE10LE-COMMON-AUDIT-KO.md](WE10LE-COMMON-AUDIT-KO.md).
