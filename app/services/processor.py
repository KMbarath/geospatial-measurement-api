"""Orchestrates: read file -> measure each feature -> persist. Drives the file status lifecycle."""
import logging
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import mapping
from sqlalchemy.orm import Session

from app.errors import GeospatialFileError
from app.models import Feature, FileStatus, MeasurementStatus, UploadedFile
from app.services import measurement
from app.services.crs import crs_label
from app.services.readers import read_geospatial_file, validate_extension

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def process_file(db: Session, record: UploadedFile, *, max_uncompressed: int,
                 max_members: int, max_features: int) -> UploadedFile:
    """Process an already-stored upload. Raises GeospatialFileError after marking FAILED."""
    record.status = FileStatus.PROCESSING.value
    db.commit()

    try:
        ext = validate_extension(record.filename)
        result = read_geospatial_file(
            Path(record.stored_path), ext, max_uncompressed=max_uncompressed, max_members=max_members
        )
        if len(result.features) > max_features:
            raise GeospatialFileError(f"File has too many features (> {max_features}).")

        rows: list[Feature] = []
        for idx, raw in enumerate(result.features):
            if raw.unsupported_reason:
                m = measurement.Measurement(MeasurementStatus.UNSUPPORTED, note=raw.unsupported_reason)
            else:
                m = measurement.measure(raw.geometry, raw.crs, raw.error)
            rows.append(Feature(
                file_id=record.id,
                idx=idx,
                layer=raw.layer,
                geometry_type=raw.geometry.geom_type if raw.geometry is not None else None,
                geometry=mapping(raw.geometry) if raw.geometry is not None else None,
                crs=crs_label(raw.crs),
                properties=raw.properties,
                measurement_status=m.status.value,
                measurement_note=m.note,
                measurement_crs=m.crs,
                measurement_method=m.method,
                area_sq_m=m.area_sq_m,
                length_m=m.length_m,
            ))

        crs_values = sorted({r.crs for r in rows})
        warnings = list(result.warnings)
        if not rows:
            warnings.append("File was read successfully but contains no features.")
        if len(crs_values) > 1:
            warnings.append(f"Layers use different CRSs: {', '.join(crs_values)}.")

        db.add_all(rows)
        record.file_type = result.file_type
        record.feature_count = len(rows)
        record.crs = crs_values[0] if len(crs_values) == 1 else ("MIXED" if crs_values else None)
        record.warnings = warnings
        record.status = FileStatus.COMPLETED.value
        record.error_message = None
        record.processed_at = _now()
        db.commit()
        return record

    except GeospatialFileError as exc:
        _mark_failed(db, record, str(exc))
        raise
    except Exception as exc:
        log.exception("Unexpected failure processing file %s", record.id)
        _mark_failed(db, record, "Unexpected internal error while processing the file.")
        raise GeospatialFileError("Unexpected internal error while processing the file.") from exc


def _mark_failed(db: Session, record: UploadedFile, message: str) -> None:
    db.rollback()
    record.status = FileStatus.FAILED.value
    record.error_message = message
    record.processed_at = _now()
    db.add(record)
    db.commit()
