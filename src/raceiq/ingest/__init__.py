"""Data ingest layer: FastF1 cache + OpenF1 + local fallbacks.

Offline-first (master instruction #6): everything is written under ``data/``
and the pipeline must run with no network access once pre-cached.
"""

from raceiq.ingest.cache_manager import (
    data_dir,
    cache_dir,
    raw_dir,
    tracks_dir,
    processed_dir,
    manifest_path,
    read_manifest,
    write_manifest,
    cache_status,
    pre_cache_sessions,
)

from raceiq.ingest.fastf1_loader import (
    SessionData,
    load_fastf1_session,
    get_lap_telemetry,
    list_cached_events,
)

from raceiq.ingest.openf1_client import (
    OPENF1_BASE,
    fetch_openf1,
    download_session,
    load_openf1_local,
    session_key_for,
    OPENF1_ENDPOINTS,
)

__all__ = [
    "data_dir", "cache_dir", "raw_dir", "tracks_dir", "processed_dir",
    "manifest_path", "read_manifest", "write_manifest", "cache_status",
    "pre_cache_sessions",
    "SessionData", "load_fastf1_session", "get_lap_telemetry", "list_cached_events",
    "OPENF1_BASE", "fetch_openf1", "download_session", "load_openf1_local",
    "session_key_for", "OPENF1_ENDPOINTS",
]
