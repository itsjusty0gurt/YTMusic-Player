# YouTube Music Desktop Local WebSocket Protocol

## Protocol V1 (Frozen)

This document is the frozen contract for protocol version 1. Implementation
must conform to it. Backward-compatible additions are allowed as described in
the Versioning section; breaking changes require a new major protocol version.

## Design rule

The music player owns playback state, metadata extraction, playback commands,
volume/mute, artwork metadata, the WebSocket server, the authentication token,
and protocol implementation.

External clients own UI, overlays, automation, variables, triggers, tasks,
formatting, artwork caching, and downstream behavior. The player does not know
or care what application is connected.

## Transport

Use a local WebSocket server bound explicitly to `127.0.0.1`. It must not bind
to `0.0.0.0` or expose the service to LAN or external interfaces.

Use PySide6 / Qt WebSockets, preferably
`PySide6.QtWebSockets.QWebSocketServer`. Networking remains in Qt's normal
event loop and must not block the UI thread. V1 does not use TLS/WSS.

## Preferred port and discovery

The preferred V1 port is `17823`.

Startup behavior:

1. Attempt to bind `127.0.0.1:17823`.
2. If unavailable, bind another available localhost port.
3. Atomically write the actual active connection information to
   `connection.json` in the application's local application-data directory.

Example:

```json
{
  "protocol_versions": [1],
  "host": "127.0.0.1",
  "port": 17823,
  "token": "...",
  "pid": 12345
}
```

The server overwrites stale data at startup and removes or invalidates it on
clean shutdown where practical. The token must never be logged. The player
owns the token and connection file; clients do not generate the token. Clients
must verify connectivity rather than assuming the file is current. Port
scanning is not part of the protocol.

## Authentication

Generate a cryptographically secure, per-install token with approximately 256
bits of entropy. Persist it in local application settings/data so ordinary
restarts do not unnecessarily change it.

The token must not be placed in the URL, appear in logs, or be sent remotely.
It is used only for this localhost protocol. Authentication is required in the
initial client handshake. Inappropriate remote browser origins should be
rejected where practical. Localhost binding remains mandatory even with
authentication.

## Client handshake

The first valid client message must be:

```json
{
  "type": "hello",
  "protocol_versions": [1],
  "client": {
    "name": "Example Client",
    "version": "1.0.0"
  },
  "auth": {
    "token": "..."
  }
}
```

`client.name` and `client.version` are informational only. The server chooses
the highest mutually supported protocol version. For V1 this is normally 1.

Successful response:

```json
{
  "type": "hello",
  "protocol_version": 1,
  "server": {
    "name": "YouTube Music Desktop",
    "version": "0.1.0"
  },
  "capabilities": {
    "commands": [
      "play",
      "pause",
      "play_pause",
      "next",
      "previous",
      "set_volume",
      "set_muted"
    ],
    "artwork_transport": "url",
    "position_sync_interval_ms": 10000
  }
}
```

Immediately after the successful server hello, the server sends a complete
current-state snapshot. If no compatible version exists, it returns an
appropriate protocol error and closes the connection cleanly.

## Canonical playback state

The WebSocket implementation consumes the application's canonical playback
state. It must not independently scrape the YouTube Music DOM.

```text
YouTube Music DOM
      ↓
Playback Bridge
      ↓
Canonical PlaybackState
      ↓
WebSocket Server
```

Commands flow in the opposite direction through the playback controller:

```text
WebSocket Server
      ↓
Playback Controller
      ↓
YouTube Music page
```

The WebSocket layer must not duplicate selectors or page-specific JavaScript.

## State message

Use complete state snapshots, not patches.

```json
{
  "type": "state",
  "protocol_version": 1,
  "sequence": 42,
  "reason": "track_changed",
  "sent_at": "2026-10-04T19:30:11.123Z",
  "metadata_available": true,
  "playback": {
    "status": "playing",
    "position_ms": 53210,
    "position_sampled_at": "2026-10-04T19:30:11.123Z",
    "duration_ms": 243000
  },
  "track": {
    "title": "Enter Sandman",
    "artist": "Metallica",
    "album": "Metallica",
    "media_id": "CD-E-LDc384",
    "artwork": {
      "url": "https://..."
    }
  },
  "audio": {
    "volume": 72,
    "muted": false
  }
}
```

Required top-level fields are `type`, `protocol_version`, `sequence`, `reason`,
`sent_at`, `metadata_available`, `playback`, `track`, and `audio`. Known but
unavailable values use JSON `null` rather than being unpredictably omitted.

## Playback status

Allowed values are `playing`, `paused`, `stopped`, and `unknown`.

`stopped` means playback is known to be stopped. `unknown` means the player
cannot currently determine playback state reliably. `unknown` must never be
converted to `stopped` merely to simplify the model.

## Track metadata

When metadata is available:

```json
{
  "title": "Enter Sandman",
  "artist": "Metallica",
  "album": "Metallica",
  "media_id": "CD-E-LDc384",
  "artwork": {
    "url": "https://..."
  }
}
```

Optional or unreliable values may be `null`, particularly `album`,
`media_id`, and artwork URL. When metadata is unavailable, `track` is `null`
and `metadata_available` is `false`.

## Artwork

V1 transports artwork as a URL only:

```json
{
  "artwork": {
    "url": "https://..."
  }
}
```

Artwork URLs are ephemeral. V1 does not implement base64 artwork, binary
WebSocket artwork, local filesystem artwork paths, or a local HTTP artwork
server.

## State updates

Push a complete state snapshot:

- immediately after successful handshake;
- when the track changes;
- when play/pause changes;
- when volume/mute changes;
- when a seek is detected;
- during periodic position synchronization;
- when another meaningful canonical state change occurs.

Informational `reason` values include `initial`, `track_changed`,
`playback_changed`, `volume_changed`, `seek`, `position_sync`, and
`state_refresh`. Clients must not reconstruct state from the reason; the full
snapshot is authoritative.

Use a monotonically increasing `sequence` number for the current server
process. It does not need to survive application restarts.

## Playback position

Expose:

```json
{
  "position_ms": 53210,
  "position_sampled_at": "2026-10-04T19:30:11.123Z",
  "duration_ms": 243000
}
```

While playing, clients may estimate current position as `position_ms` plus
elapsed time since `position_sampled_at`. While paused, clients use the fixed
sampled position.

Push a correction approximately every 10000 ms while playback is active. Do
not send one WebSocket position message every second. Immediate updates also
occur on track changes, play, pause, and detected seeks.

## Get current state

Request:

```json
{
  "type": "get_state",
  "protocol_version": 1,
  "request_id": "abc123"
}
```

The server responds with the latest complete current state and may include the
originating `request_id`.

## Commands

Format:

```json
{
  "type": "command",
  "protocol_version": 1,
  "request_id": "abc123",
  "command": "next"
}
```

`request_id` is required and treated as an opaque client identifier.

V1 commands are:

- `play`
- `pause`
- `play_pause`
- `next`
- `previous`
- `set_volume`
- `set_muted`

Command names must not be added casually.

### Set volume

```json
{
  "type": "command",
  "protocol_version": 1,
  "request_id": "abc123",
  "command": "set_volume",
  "args": {
    "volume": 65
  }
}
```

Valid range is 0–100. Invalid values are rejected rather than silently
clamped.

### Set muted

```json
{
  "type": "command",
  "protocol_version": 1,
  "request_id": "abc124",
  "command": "set_muted",
  "args": {
    "muted": true
  }
}
```

## Command results

Successful dispatch:

```json
{
  "type": "command_result",
  "protocol_version": 1,
  "request_id": "abc123",
  "command": "next",
  "ok": true
}
```

`ok: true` means the command was accepted and successfully dispatched. It does
not guarantee YouTube Music reached the requested state. Observed state
messages remain authoritative. The server must not optimistically mutate
canonical playback state because a command was accepted.

Failed dispatch example:

```json
{
  "type": "command_result",
  "protocol_version": 1,
  "request_id": "abc123",
  "command": "next",
  "ok": false,
  "error": {
    "code": "player_unavailable",
    "message": "The YouTube Music player is not currently available."
  }
}
```

Recommended V1 command error codes are `invalid_request`,
`unsupported_command`, `invalid_argument`, `player_unavailable`,
`command_failed`, and `control_disabled`. Error messages remain useful and
concise.

## Protocol errors

```json
{
  "type": "error",
  "protocol_version": 1,
  "error": {
    "code": "unsupported_message_type",
    "message": "Unknown message type."
  }
}
```

Unknown or malformed messages normally produce a protocol error without
killing an otherwise healthy authenticated connection. Repeated malformed or
abusive traffic may result in disconnection. Input size must be bounded so a
local client cannot send arbitrarily large JSON messages.

## Capabilities

Capabilities are advertised during the handshake so clients can determine
supported commands without guessing:

```json
{
  "commands": [
    "play",
    "pause",
    "play_pause",
    "next",
    "previous",
    "set_volume",
    "set_muted"
  ],
  "artwork_transport": "url",
  "position_sync_interval_ms": 10000
}
```

Commands that are not reliable must not be advertised.

## Seek

`seek` is not automatically part of V1. Add it to capabilities and
implementation only if testing proves the playback bridge implements it
reliably. Otherwise it remains deferred without changing the rest of V1.

## Multiple clients

Support multiple simultaneous localhost clients where practical. One client
disconnecting, misbehaving, or sending a failed command must not disrupt
playback, the main UI, or other clients. Playback must not depend on WebSocket
clients being connected.

## Reconnect behavior

The server maintains no client session state across connections. Reconnect is:

```text
connect → hello/authentication → server hello → full current state
```

Clients should not blindly replay uncertain commands after reconnecting,
particularly `next`, `previous`, and `play_pause`. The server does not solve
client-side retry policy.

## Versioning

The current protocol version is 1. Clients advertise supported versions as:

```json
{"protocol_versions": [1]}
```

A future client might send:

```json
{"protocol_versions": [2, 1]}
```

Within V1, backward-compatible additions include new optional fields, new
capabilities, additional optional commands, and new informational metadata.
Clients should ignore unknown JSON fields.

Breaking changes require a new major version. Examples include removing or
renaming required fields, changing units or command semantics, incompatible
authentication changes, or changing the meaning of existing values.

## Implementation responsibilities

The protocol layer owns message parsing, validation, serialization, protocol
versions, command names, and error codes.

The WebSocket server owns listening, client connections, authentication,
handshake, broadcast, and disconnect handling.

The playback bridge/controller owns YouTube Music DOM integration, metadata,
and command execution. The WebSocket server contains no page selectors or
page-specific JavaScript.

The settings/application-data layer owns token persistence, the connection
file location, and any future preferred-port configuration.

The API may start automatically with the application. The player remains
useful with no connected WebSocket clients.

## Logging

Log useful lifecycle information: server start and selected port, server stop,
client connect/disconnect, successful/rejected handshakes, and useful protocol
errors.

Do not log the authentication token, full raw authentication payload,
excessive position updates, or every state broadcast at INFO level. Logs
remain quiet during normal playback.

## Security requirements

At minimum:

- bind only to `127.0.0.1`;
- require authentication before state or command access;
- never log the token;
- reject invalid authentication;
- reject untrusted browser origins where practical;
- bound message size;
- do not crash on malformed JSON;
- expose no remote debugging or administrative endpoint.

## Deferred features

V1 does not implement LAN access, cloud relay, remote access, network
discovery, an HTTP artwork server, base64 or binary artwork, playlist
manipulation, queue editing, music search, library access, like/dislike,
shuffle, repeat, application-specific integrations, automation concepts, or
OBS-specific features.
