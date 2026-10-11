# YouTube Music Desktop

A small, standalone Windows desktop shell for the real
[YouTube Music](https://music.youtube.com) website. YouTube Music remains
responsible for sign-in, subscriptions, library data, recommendations, and
playback.

This first vertical slice provides:

- a PySide6 `QWebEngineView` loading YouTube Music;
- a persistent WebEngine profile for cookies, login, cache, and site data;
- safe saving and restoration of window position, size, and maximized state;
- close-to-tray behavior with **Show/Hide Player** and **Exit** actions;
- per-user single-instance protection;
- console logging plus a rotating log file;
- explicit application shutdown.
- an authenticated localhost WebSocket API for playback state and controls.

Global media keys, settings UI, installers, and auto-start are not implemented
yet.

## Local WebSocket API

The player starts an authenticated WebSocket service bound only to
`127.0.0.1`. It first requests port `17823`; if that port is occupied it selects
another available localhost port.

The active host, port, process ID, supported protocol versions, and per-install
authentication token are written atomically to:

```text
%LOCALAPPDATA%\YouTubeMusicDesktop\YouTubeMusicDesktop\connection.json
```

Treat this file and its token as private user data. The token is not placed in
the WebSocket URL or application logs, and clients must authenticate in their
first message. The service is not exposed to the LAN and does not use port
scanning or network discovery. The long-lived per-install token is stored in
the same directory as `api_token`; `connection.json` is removed during clean
shutdown while `api_token` remains for the next launch.

Current commands are `play`, `pause`, `play_pause`, `next`, `previous`,
`set_volume`, and `set_muted`. Seeking is not advertised in V1. State messages
include playback status and position, track metadata and artwork URL when
available, and volume/mute state.

The complete frozen contract is in [PROTOCOL.md](PROTOCOL.md).

With the player running, the development client can print the initial state:

```powershell
python .\tools\test_client.py
```

It can also send one command, for example:

```powershell
python .\tools\test_client.py --command next
python .\tools\test_client.py --command set_volume --volume 65
python .\tools\test_client.py --command set_muted --muted true
```

## Requirements

- Windows 10 or 11
- Python 3.10 or newer

## Set up and run

From PowerShell in this directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
youtube-music-desktop
```

You can also launch it without installing the command:

```powershell
python -m ytmusic_player
```

## Build for Windows

Create a self-contained, windowed application bundle with:

```powershell
python -m pip install -e ".[build]"
.\scripts\build_windows.ps1
```

The result is written to `outputs\YouTubeMusicDesktop`, and a versioned
`outputs\YouTubeMusicDesktop-<version>-windows-x64.zip` archive is created
beside it. The build embeds the application icon and Windows product/file
metadata and includes `README.md` and the frozen `PROTOCOL.md`.
Qt WebEngine is intentionally packaged as a folder rather than a single-file
executable because it relies on helper processes and runtime resources.

Windows identifies the process as `YouTubeMusicDesktop.Player`. Because pinned
taskbar shortcuts can cache older icons, use the manual validation steps in
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) after rebuilding.

## Tests

Install the test dependency and run the automated protocol suite with:

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

Closing the window hides it in the Windows notification area. Use the tray
menu's **Exit** action to stop the application completely. If the system tray
is unavailable, closing the window exits normally so the process cannot become
inaccessible.

Only one player instance runs per Windows user/session. A second launch exits
cleanly; it does not attempt to focus the existing window.

## Local data

Qt chooses the standard per-user Windows application-data location. The app
stores its WebEngine profile (including cookies and cache), window settings,
and logs there. The current log file is named `youtube-music-desktop.log`.

To troubleshoot startup, run the app from PowerShell and check both its console
output and the log file path printed during startup.

## Project structure

```text
src/ytmusic_player/
  __main__.py       python -m entry point
  main.py           process entry point
  application.py    Qt application lifecycle
  window.py         main window and system tray
  web.py            persistent WebEngine profile and view
  settings.py       safe window-state persistence
  logging_setup.py  logging configuration
  metadata.py       authoritative identity and version
  windows_identity.py Windows AppUserModelID setup
  single_instance.py per-user Qt lock-file guard
  playback_state.py canonical playback state
  playback_bridge.py YouTube Music DOM-to-state adapter
  playback_controller.py page command adapter
  protocol.py       V1 validation and serialization
  connection_info.py token and discovery-file handling
  websocket_server.py authenticated Qt WebSocket service
  resources.py      packaged window and tray icon
  assets/icons/     original PNGs and Windows icon
packaging/
  launcher.py       PyInstaller entry point
scripts/
  build_windows.ps1 repeatable Windows bundle build
tools/
  build_icons.py    regenerate the multi-size Windows icon
  build_version_info.py generate executable version resources
  test_client.py    small local protocol development client
```

The focused manual release checks are in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
