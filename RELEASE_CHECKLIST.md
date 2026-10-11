# Windows release checklist

## Player and session

- [ ] Application starts normally without a console window.
- [ ] Google login and the YouTube Music session persist after restart.
- [ ] YouTube Music playback works.
- [ ] Previous, play/pause, and next controls work.
- [ ] Volume and mute controls work.
- [ ] Closing the window hides the player in the system tray.
- [ ] A tray click and double-click restore the player reliably.
- [ ] **Exit** in the tray menu terminates the process and removes the tray icon.
- [ ] A second launch exits cleanly while the first instance remains functional.

## Windows identity and icons

Windows can retain an old icon in an existing pinned shortcut. Do not clear the
system icon cache. Instead, unpin the old entry before validating a rebuilt app.

- [ ] Unpin any older YouTube Music Desktop taskbar entry.
- [ ] Launch the rebuilt `YouTubeMusicDesktop.exe`.
- [ ] Pin the rebuilt application from its running taskbar entry.
- [ ] The executable icon is correct in File Explorer.
- [ ] The taskbar and newly pinned taskbar icons are correct.
- [ ] The Alt+Tab icon is correct.
- [ ] The window title-bar icon is correct.
- [ ] The notification-area icon is correct.

## Local WebSocket API

- [ ] A client connects through the current `connection.json` information.
- [ ] The authenticated hello receives an initial complete playback state.
- [ ] Playback commands still work and return command results.
- [ ] Active-track and playback state updates arrive.
- [ ] Restart and reconnect work.
- [ ] `connection.json` is removed after a clean exit.

## Release contents

- [ ] The bundle contains `README.md`, `PROTOCOL.md`, icons, Qt WebEngine, and
      Qt WebSockets runtime files.
- [ ] The bundle contains no token, connection file, logs, browser profile,
      cookies, Google/YouTube session data, `.venv`, test cache, local
      attachments, or build-time temporary files.
