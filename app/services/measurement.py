"""Measurement calculation: area for polygons, length for lines, graceful for the rest."""
from dataclasses import dataclass

import numpy as np
import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from app.models import MeasurementStatus
from app.services import crs as crs_utils

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString", "LinearRing"}
NO_MEASURE_TYPES = {"Point", "MultiPoint"}

# Beyond this lon/lat extent, a single UTM zone / local projection gets noticeably less accurate.
WIDE_EXTENT_DEGREES = 10.0


@dataclass
class Measurement:
    status: MeasurementStatus
    area_sq_m: float | None = None
    length_m: float | None = None
    crs: str | None = None        # the projected CRS used
    method: str | None = None
    note: str | None = None


def _reproject(geom: BaseGeometry, tr) -> BaseGeometry:
    def fn(coords: np.ndarray) -> np.ndarray:
        x, y = tr.transform(coords[:, 0], coords[:, 1])
        return np.column_stack((x, y))
    return shapely.transform(geom, fn)


def _project(geom_wgs84: BaseGeometry, target: crs_utils.ProjectedCRS) -> BaseGeometry:
    tr = crs_utils.get_transformer(crs_utils.WGS84, target.crs)
    return _reproject(geom_wgs84, tr)


def _to_wgs84(geom: BaseGeometry, src: CRS) -> BaseGeometry:
    if crs_utils.is_wgs84(src):
        return geom
    tr = crs_utils.get_transformer(src, crs_utils.WGS84)
    return _reproject(geom, tr)


def measure(geom: BaseGeometry | None, src_crs: CRS | None, error: str | None = None) -> Measurement:
    """Measure one geometry. Never raises: every failure is reported through ``status``/``note``."""
    if error:
        return Measurement(MeasurementStatus.FAILED, note=error)
    if geom is None:
        return Measurement(MeasurementStatus.UNSUPPORTED, note="Feature has no geometry.")
    if geom.is_empty:
        return Measurement(MeasurementStatus.UNSUPPORTED, note="Geometry is empty.")

    gtype = geom.geom_type
    if gtype in NO_MEASURE_TYPES:
        return Measurement(MeasurementStatus.NOT_APPLICABLE, note="No measurement is defined for points.")
    if gtype not in AREA_TYPES | LENGTH_TYPES:
        return Measurement(
            MeasurementStatus.UNSUPPORTED,
            note=f"Measurement is not supported for geometry type '{gtype}'.",
        )
    if src_crs is None:
        return Measurement(
            MeasurementStatus.FAILED,
            note="Source CRS is unknown (no .prj and coordinates are not lon/lat); cannot measure safely.",
        )

    try:
        geom2d = shapely.force_2d(geom)
        wgs = _to_wgs84(geom2d, src_crs)
        minx, miny, maxx, maxy = wgs.bounds
        if not all(map(_finite, (minx, miny, maxx, maxy))):
            return Measurement(MeasurementStatus.FAILED, note="Coordinates could not be transformed to WGS84.")
        if not (-180.0 <= minx and maxx <= 180.0 and -90.0 <= miny and maxy <= 90.0):
            return Measurement(MeasurementStatus.FAILED, note="Coordinates fall outside valid lon/lat ranges.")

        lon, lat = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        notes: list[str] = []
        if max(maxx - minx, maxy - miny) > WIDE_EXTENT_DEGREES:
            notes.append(
                f"Feature spans more than {WIDE_EXTENT_DEGREES:.0f} degrees; "
                "accuracy of a single local projection is reduced."
            )
        if gtype in AREA_TYPES and not geom2d.is_valid:
            notes.append(f"Invalid polygon geometry ({explain_validity(geom2d)}); area may be unreliable.")

        if gtype in AREA_TYPES:
            target = crs_utils.laea_crs(lon, lat)
            area = _project(wgs, target).area
            return Measurement(
                MeasurementStatus.MEASURED, area_sq_m=round(area, 4), crs=target.label,
                method=target.method, note=" ".join(notes) or None,
            )

        target = crs_utils.utm_crs(lon, lat)
        length = _project(wgs, target).length
        return Measurement(
            MeasurementStatus.MEASURED, length_m=round(length, 4), crs=target.label,
            method=target.method, note=" ".join(notes) or None,
        )
    except Exception as exc:  # pyproj / shapely edge cases must never crash the request
        return Measurement(MeasurementStatus.FAILED, note=f"Measurement failed: {exc}")


def _finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))
