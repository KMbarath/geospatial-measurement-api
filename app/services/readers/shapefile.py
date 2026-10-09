"""Shapefile reader built on pyshp (pure Python) + shapely + pyproj."""
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import shapefile  # pyshp
from pyproj import CRS
from shapely.geometry import shape as shapely_shape

from app.errors import GeospatialFileError
from app.services.readers.base import RawFeature, ReadResult
from app.services.readers.properties import sanitize

SHP_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg")


def group_shapefile_members(zf: zipfile.ZipFile) -> dict[str, dict[str, zipfile.ZipInfo]]:
    """Group archive members by '<dir>/<stem>' -> {ext: ZipInfo}. Skips junk and unsafe paths."""
    groups: dict[str, dict[str, zipfile.ZipInfo]] = {}
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            continue  # zip-slip attempt; we never write using archive names anyway
        if "__MACOSX" in path.parts or path.name.startswith("."):
            continue
        ext = path.suffix.lower()
        if ext in SHP_PARTS:
            groups.setdefault(str(path.with_suffix("")), {})[ext] = info
    return {k: v for k, v in groups.items() if ".shp" in v}


def _parse_prj(text: str) -> CRS | None:
    try:
        return CRS.from_wkt(text)
    except Exception:
        try:
            return CRS.from_user_input(text.strip())
        except Exception:
            return None


def _looks_geographic(bbox: list[float] | tuple[float, ...] | None) -> bool:
    if not bbox or len(bbox) < 4:
        return False
    minx, miny, maxx, maxy = bbox[:4]
    return -180.0 <= minx <= maxx <= 180.0 and -90.0 <= miny <= maxy <= 90.0


def read_shapefile_zip(zf: zipfile.ZipFile) -> ReadResult:
    groups = group_shapefile_members(zf)
    if not groups:
        raise GeospatialFileError("No .shp file found in the archive.")

    result = ReadResult(file_type="shapefile")
    with tempfile.TemporaryDirectory(prefix="shp_") as tmp:
        for n, (stem, parts) in enumerate(sorted(groups.items())):
            layer = PurePosixPath(stem).name
            base = Path(tmp) / f"layer{n}"  # generated names: archive paths never touch the filesystem
            for ext, info in parts.items():
                with zf.open(info) as src, open(f"{base}{ext}", "wb") as dst:
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)
            _read_layer(base, layer, parts, result)
    return result


def _read_layer(base: Path, layer: str, parts: dict, result: ReadResult) -> None:
    crs: CRS | None = None
    prj_path = Path(f"{base}.prj")
    if ".prj" in parts:
        crs = _parse_prj(prj_path.read_text(errors="replace"))
        if crs is None:
            result.warnings.append(f"Layer '{layer}': .prj could not be parsed; CRS unknown.")

    encoding = "utf-8"
    if ".cpg" in parts:
        encoding = Path(f"{base}.cpg").read_text(errors="replace").strip() or "utf-8"
    if ".dbf" not in parts:
        result.warnings.append(f"Layer '{layer}': .dbf missing; features have no attributes.")
    if ".shx" not in parts:
        result.warnings.append(f"Layer '{layer}': .shx missing; read sequentially from .shp.")

    try:
        reader = shapefile.Reader(str(base), encoding=encoding, encodingErrors="replace")
    except Exception as exc:
        raise GeospatialFileError(f"Layer '{layer}' is not a readable shapefile: {exc}") from exc

    with reader:
        if ".prj" not in parts:
            if _looks_geographic(getattr(reader, "bbox", None)):
                crs = CRS.from_epsg(4326)
                result.warnings.append(
                    f"Layer '{layer}': no .prj; coordinates look like lon/lat so EPSG:4326 was assumed."
                )
            else:
                result.warnings.append(
                    f"Layer '{layer}': no .prj and coordinates are not lon/lat; CRS unknown, features not measured."
                )

        field_names = [f[0] for f in reader.fields[1:]]
        try:
            for i, sr in enumerate(reader.iterShapeRecords()):
                result.features.append(_feature(layer, crs, sr, field_names, i))
        except Exception as exc:
            raise GeospatialFileError(f"Layer '{layer}' is corrupt near record {len(result.features)}: {exc}") from exc


def _feature(layer: str, crs: CRS | None, sr, field_names: list[str], i: int) -> RawFeature:
    try:
        props = sanitize(dict(zip(field_names, list(sr.record)))) if field_names else {}
    except Exception:
        props = {}

    shp = sr.shape
    if shp.shapeType == shapefile.NULL:
        return RawFeature(layer, None, crs, props)
    try:
        geom = shapely_shape(shp.__geo_interface__)
    except Exception as exc:
        return RawFeature(layer, None, crs, props, error=f"Invalid geometry in record {i}: {exc}")
    return RawFeature(layer, geom, crs, props)
