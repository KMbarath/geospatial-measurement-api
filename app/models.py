"""ORM models: one uploaded file has many features."""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # stored as naive UTC


class FileStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementStatus(str, enum.Enum):
    MEASURED = "MEASURED"              # area / length computed
    NOT_APPLICABLE = "NOT_APPLICABLE"  # e.g. Point - nothing to measure
    UNSUPPORTED = "UNSUPPORTED"        # geometry we deliberately do not measure
    FAILED = "FAILED"                  # measurement attempted but could not be done


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(1024))
    file_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # shapefile | kml | kmz
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=FileStatus.PENDING.value, index=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    features: Mapped[list["Feature"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Feature.idx",
    )


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (Index("ix_features_file_idx", "file_id", "idx"),)

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("uploaded_files.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer)                      # 0-based index within the file
    layer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geometry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GeoJSON, in the *source* CRS
    crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)

    measurement_status: Mapped[str] = mapped_column(String(16))
    measurement_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    measurement_crs: Mapped[str | None] = mapped_column(String(512), nullable=True)
    measurement_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    area_sq_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    file: Mapped[UploadedFile] = relationship(back_populates="features")

    @property
    def feature_id(self) -> int:
        return self.idx
