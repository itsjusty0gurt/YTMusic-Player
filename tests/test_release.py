from __future__ import annotations

from ytmusic_player import __version__
from ytmusic_player.build_identity import BuildIdentity, current_build_identity
from ytmusic_player.metadata import APP_USER_MODEL_ID, APP_VERSION
from ytmusic_player.protocol import SERVER_VERSION
from ytmusic_player.single_instance import SingleInstanceLock


def test_release_version_has_one_authoritative_value() -> None:
    assert APP_VERSION == "0.1.0"
    assert __version__ == APP_VERSION
    assert SERVER_VERSION == APP_VERSION


def test_windows_application_identity_is_stable() -> None:
    assert APP_USER_MODEL_ID == "YouTubeMusicDesktop.Player"


def test_source_run_has_identifiable_development_build() -> None:
    identity = current_build_identity()
    assert identity == BuildIdentity()
    assert identity.source_id == "development-dirty"


def test_single_instance_lock_rejects_competitor_and_can_be_reacquired(tmp_path) -> None:
    lock_path = tmp_path / "instance.lock"
    first = SingleInstanceLock(lock_path)
    second = SingleInstanceLock(lock_path)

    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()
