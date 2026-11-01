# WE10LE memory-card season negotiation v3

This community extension applies only to the Korean WE10LE MAIN service. It
compares client-declared runtime identities before a match; it does not attest
RAM contents, supply roster data, replace peer UDP traffic, or prove a two-PC
gameplay session. A matching client implementation and the updated server are
both required. No remote deployment is implied by these source changes.

All integers below use network byte order. Transport framing, XOR, sequence
counters and MD5 are the existing WE10LE framing. Native request `4373` remains
four bytes (`teamID`, original unknown uint16); no extension data occupies its
unknown field. Each seasonal team continues to send its native base team ID,
not a virtual clone ID. The Chelsea example sends base69.

## Request 4F10: exactly48 bytes

| Offset | Size | Value |
| --- | --- | --- |
| 0 | 4 | ASCII `W10S` |
| 4 | 2 | version3 |
| 6 | 2 | flags0; other values rejected |
| 8 | 32 | opaque identity, not all zero |
| 40 | 2 | native base teamID |
| 42 | 2 | season0=Original;1–65534=explicit catalog season code |
| 44 | 4 | nonzero request nonce |

Version3 accepts native base IDs0–295 for Original and club IDs64–203 for a
nonzero season. Season65535 is reserved and rejected. The pair `(base,season)`
identifies an entry in the client's validated memory-card catalog; the same
season number may be used by different clubs. Version2 declarations are rejected.

The current client computes SHA256 of its engine/protocol digest, the SHA256 of
the complete validated `ROSTERS.BIN` file, and six actual loaded Original data
buffers (team records, players, club names, rosters, kits, custom logos), in that
order. The card pack separately binds its five baseline tables; mutable team
records are not part of that stored baseline hash. Whole-card `.ps2` bytes,
filesystem timestamps, and card filenames are not the multiplayer identity.

The server treats the identity as an opaque32-byte declaration and compares all
32 bytes exactly; it neither calculates that runtime identity nor attests the
client's RAM or card contents. It checks the numeric base/season ranges but does
not hold or verify the catalog. The client must reject a nonzero `(base,season)`
pair absent from its validated catalog, including a peer choice in a reply.
Adding card entries within this format therefore needs no server allowlist
change. Both peers still require identical validated pack content, engine, and
loaded Original data. The example pack contains Chelsea2010–11 as `(69,1)`.

Send once after MAIN authentication and again on each committed seasonal choice.
Each actual send advances a nonzero32-bit nonce; idempotent requests also serve as
polling. Authentication is required; a profile
or lobby need not have been selected yet. Declarations are connection-local and
are not stored in the database or substituted for account/password hashes.

## Response 4F11: exactly84 bytes

| Offset | Size | Value |
| --- | --- | --- |
| 0 | 4 | ASCII `W10S` |
| 4 | 2 | version3 |
| 6 | 2 | status below |
| 8 | 32 | recipient identity echo; zero if no valid declaration |
| 40 | 4 | current roomID, or0 outside a room |
| 44 | 4 | participating entry count0–4 |
| 48 | 32 | four fixed8-byte entries: profileID:u32,base:u16,season:u16 |
| 80 | 4 | recipient's latest nonzero request nonce |

Version3 season matches support exactly two participants (1v1). The four fixed
slots reserve format capacity and can describe an invalid larger set in an error
response; they do not enable season 2v2. Legacy four-player behavior is unchanged.
The recipient is entry0 when participating. Other participants follow in ascending
profileID order. Unused entries are zero. Outside a room, or while not a
participant, count is0 and all entries are zero. A peer without an active MAIN
connection has baseFFFF/season0 if represented in an error snapshot. Previous
choices can remain in an error-status snapshot after identity revocation; those
entries must not be used for preparation. Room spectators do not
receive participant entries for preparation. Clients must not hydrate a roster
from count0, a status other than6, or an identity echo that differs from their own.

| Status | Meaning |
| --- | --- |
| 0 | accepted declaration/current matching snapshot; not final for preparation |
| 1 | participant identities or native team choices differ |
| 2 | a peer has no valid negotiation, or fewer than two mod participants |
| 3 | malformed request/unsupported version,flags,season,base,zero identity,or more than two mod participants |
| 4 | authentication/scope unavailable |
| 5 | a differing selection is locked after team selection |
| 6 | both current-round native team requests received; frozen final snapshot |

An older server's common fallback is `4F11` with **four zero bytes**. It must never
be accepted as negotiation: require exact84-byte length, magic, version, identity
echo, a valid entry count and the correct local/peer base choices. Native roster
preparation additionally requires status6 and the nonce from the client's fresh
preparation poll; an older queued response cannot satisfy that fresh nonce.

## Lifecycle and enforcement

Legacy-to-legacy rooms retain the shared PES6 behavior and receive no unsolicited
extension packets. Once a participant uses the extension, mixed legacy/mod or
different-identity participants cannot join that participating set. Membership is
checked again on `4360` start and `436F` readiness. Mod start requires exactly two
participants. A third mod participant is rejected; a larger legacy set that later
uses negotiation cannot start as a season match. Failure uses the original request's status response and does not
advance room phase.

`4360` precedes side/settings/team selection. Declarations can therefore change
through phase4 (team selection). A changed declaration clears the shared ready
count. At phase4 readiness, both native captain teamIDs must match declared base
choices. Original season0 follows the actual native `4373` teamID automatically;
a nonzero season rejects a team other than its declared base until another
explicit matching declaration is made. The client's catalog checks that pair.

Only actual phase4 `4373` requests create per-client submissions, keyed to the
room object, current identity and current choice. Once both matching submissions
exist, the server freezes choices and sends status6 to both clients before the
vanilla `4374` ACK/room update. A differing declaration is then rejected even in
phase4. An identity-only status0 never authorizes native roster preparation.

During phases5–7 (kit selection through match), differing identity/base/season
declarations and differing native team selections are rejected. Idempotent polls
with fresh nonces remain accepted and retain the final submissions. New starts,
different-teams rematches, team-selection reentry and membership changes clear old
submissions; old native team IDs alone cannot finalize a new round. A same-teams
rematch explicitly reuses the frozen submissions only after current participant,
identity, choice and captain-base validation; its client still requires a fresh
nonce response. Malformed declarations
revoke the old identity rather than silently retaining a previously valid one.

Only clients that used `4F10` receive snapshots. Membership/choice changes,
forced cancellation and room exit update those snapshots. Exiting a room removes
participation and clears the per-room selection; the connection identity remains
available for the next room. Logical logout and connection loss clear all
negotiation state. No account-row hash is changed.

## Verification scope

`tests/test_we10le_season_negotiation.py` uses real WE10LE encryption/framing,
Twisted transports/Deferreds, authentication, user/lobby/room models and inherited
PES6 handlers. Only database/clock boundaries use the existing in-memory fixture.
It covers two-participant snapshots, v3's two-player limit and legacy four-player compatibility,
mismatch/retry, malformed requests, phase locks, native base choice checks,
final confirmation ordering, fresh recipient nonces, both rematch paths and
cleanup. Generic club/season cases cover catalog choices beyond Chelsea,
club-range boundaries, reserved season65535 and incompatible version2.
The recorded full server run contains 205 passing Python tests. These are server
protocol tests; two machines still require validation
of client callbacks, native roster preparation, UDP connectivity and gameplay.
