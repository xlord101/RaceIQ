"""Track segmentation and circuit geometry."""

from raceiq.track.segmentation import (
    TrackGeometry,
    build_segments,
    segments_from_telemetry,
    geometry_from_circuit_info,
    mark_key_acceleration_zones,
    longest_straight,
    segments_to_frame,
    max_legal_deploy_kw,
)

__all__ = [
    "TrackGeometry", "build_segments", "segments_from_telemetry",
    "geometry_from_circuit_info", "mark_key_acceleration_zones",
    "longest_straight", "segments_to_frame", "max_legal_deploy_kw",
]
