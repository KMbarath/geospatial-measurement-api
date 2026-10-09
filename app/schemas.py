"""Pydantic response models."""
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field, field_serializer


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


class FileOut(_ORM):
    id: str
    filename: str
    file_type: str | None = None
    size_bytes: int
    feature_count: int
    crs: str | None = None
    status: str
    error_message: str | None = None
    warnings: list[str] = []
    created_at: datetime
    processed_at: datetime | None = None

    @field_serializer("created_at", "processed_at")
    def _ser_dt(self, v: datetime | None) -> str | None:
        return _utc(v)


class FileListOut(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[FileOut]


class UploadFailedOut(FileOut):
    detail: str


class MeasurementOut(_ORM):
    feature_id: int
    layer: str | None = None
    geometry_type: str | None = None
    crs: str | None = None
    measurement_status: str
    area_sq_m: float | None = None
    length_m: float | None = None
    measurement_crs: str | None = None
    measurement_method: str | None = None
    measurement_note: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def area_hectares(self) -> float | None:
        return None if self.area_sq_m is None else round(self.area_sq_m / 10_000, 6)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def area_sq_km(self) -> float | None:
        return None if self.area_sq_m is None else round(self.area_sq_m / 1_000_000, 8)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def length_km(self) -> float | None:
        return None if self.length_m is None else round(self.length_m / 1000, 6)


class FeatureOut(MeasurementOut):
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] = {}


class MeasurementSummary(BaseModel):
    feature_count: int
    by_geometry_type: dict[str, int]
    by_measurement_status: dict[str, int]
    total_area_sq_m: float
    total_area_hectares: float
    total_length_m: float
    total_length_km: float


class MeasurementsOut(BaseModel):
    file_id: str
    filename: str
    crs: str | None
    summary: MeasurementSummary
    total: int
    limit: int
    offset: int
    results: list[MeasurementOut]


class FeaturesOut(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    results: list[FeatureOut]
