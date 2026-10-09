"""Builders for in-memory Shapefile zips and KML documents used by tests and the sample script."""
import io
import zipfile

import shapefile
from pyproj import CRS


def prj_wkt(epsg: int) -> str:
    return CRS.from_epsg(epsg).to_wkt(version="WKT1_ESRI")


def make_shapefile_zip(
    shapes: list[dict], *, shape_type: int, epsg: int | None = 4326, fields=(("name", "C", 40),),
    stem: str = "layer", records: list[tuple] | None = None, extra_files: dict[str, bytes] | None = None,
    with_shx: bool = True, with_dbf: bool = True,
) -> bytes:
    """`shapes` are GeoJSON-like dicts understood by pyshp's Writer.shape()."""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shape_type) as w:
        for f in fields:
            w.field(*f)
        for i, geo in enumerate(shapes):
            w.shape(geo) if geo is not None else w.null()
            w.record(*(records[i] if records else (f"feature-{i}",)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stem}.shp", shp.getvalue())
        if with_shx:
            zf.writestr(f"{stem}.shx", shx.getvalue())
        if with_dbf:
            zf.writestr(f"{stem}.dbf", dbf.getvalue())
        if epsg is not None:
            zf.writestr(f"{stem}.prj", prj_wkt(epsg))
        for name, data in (extra_files or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def box(minx, miny, maxx, maxy):
    return [[(minx, miny), (minx, maxy), (maxx, maxy), (maxx, miny), (minx, miny)]]  # clockwise (outer)


def polygon_geo(rings):
    return {"type": "Polygon", "coordinates": rings}


def kml_doc(placemarks: str, name: str = "test") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>{name}</name>{placemarks}</Document></kml>"
    ).encode()


def kml_polygon(coords: str, name="poly", inner: str | None = None, extra: str = "") -> str:
    inner_xml = (f"<innerBoundaryIs><LinearRing><coordinates>{inner}</coordinates></LinearRing></innerBoundaryIs>"
                 if inner else "")
    return (f"<Placemark><name>{name}</name>{extra}<Polygon><outerBoundaryIs><LinearRing>"
            f"<coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs>{inner_xml}</Polygon></Placemark>")


def kml_line(coords: str, name="line") -> str:
    return f"<Placemark><name>{name}</name><LineString><coordinates>{coords}</coordinates></LineString></Placemark>"


def kml_point(coords: str, name="pt") -> str:
    return f"<Placemark><name>{name}</name><Point><coordinates>{coords}</coordinates></Point></Placemark>"
