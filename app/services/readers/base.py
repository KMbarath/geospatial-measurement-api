"""Format-agnostic structures produced by the readers."""
from dataclasses import dataclass, field
from typing import Any

from pyproj import CRS
from shapely.geometry.base import BaseGeometry


@dataclass
class RawFeature:
    layer: str | None
    geometry: BaseGeometry | None
    crs: CRS | None
    properties: dict[str, Any] = field(default_factory=dict)
    error: str | None = None               # this one feature could not be parsed
    unsupported_reason: str | None = None  # geometry kind we recognise but do not handle


@dataclass
class ReadResult:
    file_type: str  # shapefile | kml | kmz
    features: list[RawFeature] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
