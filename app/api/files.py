"""/api/files endpoints."""
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import FileTooLargeError, GeospatialFileError, UnsupportedFileTypeError
from app.models import Feature, FileStatus, UploadedFile
from app.schemas import (
    FeatureOut, FeaturesOut, FileListOut, FileOut, MeasurementOut, MeasurementsOut, MeasurementSummary,
    UploadFailedOut,
)
from app.services import storage
from app.services.processor import process_file
from app.services.readers import validate_extension

router = APIRouter(prefix="/api/files", tags=["files"])

DB = Annotated[Session, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=10_000, description="Page size")]
Offset = Annotated[int, Query(ge=0, description="Number of items to skip")]


def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"File '{file_id}' not found.")
    return record


def _require_completed(record: UploadedFile) -> None:
    if record.status != FileStatus.COMPLETED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"File is not ready (status={record.status})."
            + (f" {record.error_message}" if record.error_message else ""),
        )


@router.post(
    "/", response_model=FileOut, status_code=status.HTTP_201_CREATED, summary="Upload and process a file",
    responses={
        413: {"description": "File too large"},
        415: {"description": "Unsupported file type"},
        422: {"model": UploadFailedOut, "description": "File accepted but could not be processed (status FAILED)"},
    },
)
def upload_file(
    request: Request, db: DB,
    file: Annotated[UploadFile, File(description="A .zip containing a Shapefile, or a .kml file")],
):
    settings = request.app.state.settings
    filename = storage.clean_filename(file.filename)
    try:
        validate_extension(filename)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    file_id = uuid.uuid4().hex
    directory = Path(settings.storage_dir) / file_id
    try:
        path, size = storage.save_upload(file, directory, filename, settings.max_upload_bytes)
    except FileTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc

    record = UploadedFile(id=file_id, filename=filename, stored_path=str(path), size_bytes=size,
                          status=FileStatus.PENDING.value)
    db.add(record)
    db.commit()

    try:
        process_file(
            db, record,
            max_uncompressed=settings.max_uncompressed_bytes,
            max_members=settings.max_archive_members,
            max_features=settings.max_features,
        )
    except GeospatialFileError as exc:
        body = UploadFailedOut(**FileOut.model_validate(record).model_dump(), detail=str(exc))
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))
    return record


@router.get("/", response_model=FileListOut, summary="List uploaded files")
def list_files(db: DB, limit: Limit = 50, offset: Offset = 0):
    total = db.scalar(select(func.count()).select_from(UploadedFile)) or 0
    rows = db.scalars(
        select(UploadedFile).order_by(UploadedFile.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return FileListOut(total=total, limit=limit, offset=offset, results=rows)


@router.get("/{file_id}/", response_model=FileOut, summary="File information")
def get_file(file_id: str, db: DB):
    return _get_file_or_404(db, file_id)


def _filtered(file_id: str, geometry_type: str | None, measurement_status: str | None, layer: str | None):
    stmt = select(Feature).where(Feature.file_id == file_id)
    if geometry_type:
        stmt = stmt.where(func.lower(Feature.geometry_type) == geometry_type.lower())
    if measurement_status:
        stmt = stmt.where(Feature.measurement_status == measurement_status.upper())
    if layer:
        stmt = stmt.where(Feature.layer == layer)
    return stmt


def _summary(db: Session, stmt) -> MeasurementSummary:
    sub = stmt.subquery()
    total, area, length = db.execute(
        select(func.count(), func.coalesce(func.sum(sub.c.area_sq_m), 0.0),
               func.coalesce(func.sum(sub.c.length_m), 0.0))
    ).one()
    by_type = dict(db.execute(
        select(func.coalesce(sub.c.geometry_type, "None"), func.count()).group_by(sub.c.geometry_type)
    ).all())
    by_status = dict(db.execute(
        select(sub.c.measurement_status, func.count()).group_by(sub.c.measurement_status)
    ).all())
    return MeasurementSummary(
        feature_count=total, by_geometry_type=by_type, by_measurement_status=by_status,
        total_area_sq_m=round(area, 4), total_area_hectares=round(area / 10_000, 6),
        total_length_m=round(length, 4), total_length_km=round(length / 1000, 6),
    )


@router.get("/{file_id}/measurements/", response_model=MeasurementsOut, summary="Measurements per feature")
def get_measurements(
    file_id: str, db: DB, limit: Limit = 1000, offset: Offset = 0,
    geometry_type: Annotated[str | None, Query(description="e.g. Polygon, LineString")] = None,
    measurement_status: Annotated[str | None, Query(description="MEASURED | NOT_APPLICABLE | UNSUPPORTED | FAILED")] = None,
    layer: str | None = None,
):
    record = _get_file_or_404(db, file_id)
    _require_completed(record)
    stmt = _filtered(file_id, geometry_type, measurement_status, layer)
    page = db.scalars(stmt.order_by(Feature.idx).limit(limit).offset(offset)).all()
    summary = _summary(db, stmt)
    return MeasurementsOut(
        file_id=record.id, filename=record.filename, crs=record.crs, summary=summary,
        total=summary.feature_count, limit=limit, offset=offset,
        results=[MeasurementOut.model_validate(f) for f in page],
    )


@router.get("/{file_id}/features/", response_model=FeaturesOut, summary="Features with geometry and properties")
def get_features(
    file_id: str, db: DB, limit: Limit = 100, offset: Offset = 0,
    geometry_type: str | None = None, measurement_status: str | None = None, layer: str | None = None,
):
    record = _get_file_or_404(db, file_id)
    _require_completed(record)
    stmt = _filtered(file_id, geometry_type, measurement_status, layer)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = db.scalars(stmt.order_by(Feature.idx).limit(limit).offset(offset)).all()
    return FeaturesOut(file_id=record.id, total=total, limit=limit, offset=offset,
                       results=[FeatureOut.model_validate(f) for f in page])


@router.delete("/{file_id}/", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a file and its features")
def delete_file(file_id: str, request: Request, db: DB):
    record = _get_file_or_404(db, file_id)
    storage.delete_upload_dir(Path(record.stored_path).parent)
    db.delete(record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
