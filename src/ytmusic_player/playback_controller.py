from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWebEngineCore import QWebEnginePage

from .playback_commands import PLAYBACK_COMMANDS


CommandCallback = Callable[[bool, str | None, str | None], None]


class PlaybackController(QObject):
    """Dispatch validated commands to the YouTube Music page."""

    supported_commands = PLAYBACK_COMMANDS

    def __init__(self, page: QWebEnginePage, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._page = page
        self._available = False
        page.loadStarted.connect(self._on_load_started)
        page.loadFinished.connect(self._on_load_finished)

    def dispatch(
        self,
        command: str,
        args: dict[str, Any],
        callback: CommandCallback,
    ) -> None:
        if not self._available:
            callback(False, "player_unavailable", "The YouTube Music player is not currently available.")
            return

        payload = json.dumps({"command": command, "args": args}, separators=(",", ":"))
        script = _command_script(payload)
        self._page.runJavaScript(script, lambda result: self._handle_result(result, callback))

    def _on_load_started(self) -> None:
        self._available = False

    def _on_load_finished(self, success: bool) -> None:
        self._available = success

    @staticmethod
    def _handle_result(result: Any, callback: CommandCallback) -> None:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                result = None
        if isinstance(result, dict) and result.get("ok") is True:
            callback(True, None, None)
            return
        if isinstance(result, dict):
            code = result.get("code")
            message = result.get("message")
            if isinstance(code, str) and isinstance(message, str):
                callback(False, code, message)
                return
        callback(False, "command_failed", "The playback command could not be dispatched.")


def _command_script(payload: str) -> str:
    return f"""
JSON.stringify((() => {{
  const request = {payload};
  const video = document.querySelector('video');
  if (!video) return {{ok: false, code: 'player_unavailable', message: 'The YouTube Music player is not currently available.'}};

  const findPlayerControl = (label) => {{
    const bar = document.querySelector('ytmusic-player-bar');
    if (!bar) return null;

    const normalizedLabel = label.toLocaleLowerCase();
    const matchesLabel = (node) => [
      node.getAttribute('aria-label'),
      node.getAttribute('title')
    ].some((value) => typeof value === 'string'
      && value.trim().toLocaleLowerCase() === normalizedLabel);
    const isUsable = (node) => node
      && node.isConnected
      && node.disabled !== true
      && node.getAttribute('aria-disabled') !== 'true'
      && !node.closest('[disabled], [aria-disabled="true"]');

    const semanticButton = Array.from(
      bar.querySelectorAll('button, [role="button"]')
    ).find((node) => matchesLabel(node) && isUsable(node));
    if (semanticButton) return semanticButton;

    const semanticHost = Array.from(
      bar.querySelectorAll('yt-icon-button[title]')
    ).find((node) => matchesLabel(node) && isUsable(node));
    if (semanticHost) {{
      const innerButton = semanticHost.querySelector('button, [role="button"]');
      return isUsable(innerButton) ? innerButton : semanticHost;
    }}

    const fallbackSelector = label === 'Next' ? '.next-button' : '.previous-button';
    const fallbackHost = bar.querySelector(fallbackSelector);
    if (!isUsable(fallbackHost)) return null;
    const fallbackButton = fallbackHost.querySelector('button, [role="button"]');
    return isUsable(fallbackButton) ? fallbackButton : fallbackHost;
  }};

  try {{
    switch (request.command) {{
      case 'play':
        if (video.paused) video.play();
        return {{ok: true}};
      case 'pause':
        if (!video.paused) video.pause();
        return {{ok: true}};
      case 'play_pause':
        if (video.paused) video.play(); else video.pause();
        return {{ok: true}};
      case 'next': {{
        const button = findPlayerControl('Next');
        if (!button) return {{ok: false, code: 'player_unavailable', message: 'Next track control is unavailable.'}};
        button.click();
        return {{ok: true}};
      }}
      case 'previous': {{
        const button = findPlayerControl('Previous');
        if (!button) return {{ok: false, code: 'player_unavailable', message: 'Previous track control is unavailable.'}};
        button.click();
        return {{ok: true}};
      }}
      case 'set_volume':
        video.volume = request.args.volume / 100;
        video.dispatchEvent(new Event('volumechange'));
        return {{ok: true}};
      case 'set_muted':
        video.muted = request.args.muted;
        video.dispatchEvent(new Event('volumechange'));
        return {{ok: true}};
      default:
        return {{ok: false, code: 'unsupported_command', message: 'Unsupported playback command.'}};
    }}
  }} catch (_) {{
    return {{ok: false, code: 'command_failed', message: 'The playback command could not be dispatched.'}};
  }}
}})())
"""
