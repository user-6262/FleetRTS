"""Client-side networking helpers (stdlib only). Used by the pygame demo; no pygame imports here."""

from .app_messages import (
    HOST_CONFIG,
    LOBBY_CHAT,
    LOBBY_PRESENCE,
    LOBBY_READY,
    START_MATCH,
    host_config,
    lobby_chat,
    lobby_presence,
    lobby_ready,
    start_match,
)
from .http_client import (
    FleetHttpError,
    create_lobby,
    get_lobby,
    get_lobby_by_short_id,
    join_lobby,
    list_lobbies,
    quick_join,
)
from .relay_client import RelayClient

__all__ = [
    "HOST_CONFIG",
    "LOBBY_CHAT",
    "LOBBY_READY",
    "LOBBY_PRESENCE",
    "START_MATCH",
    "FleetHttpError",
    "create_lobby",
    "get_lobby",
    "get_lobby_by_short_id",
    "join_lobby",
    "list_lobbies",
    "quick_join",
    "host_config",
    "lobby_chat",
    "lobby_presence",
    "lobby_ready",
    "start_match",
    "RelayClient",
]
