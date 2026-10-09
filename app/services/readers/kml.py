"""Dependency-light KML reader (stdlib + defusedxml + shapely).

Supports Placemarks at any nesting depth (Document/Folder), Point, LineString, LinearRing,
Polygon (with inner boundaries), MultiGeometry (nested), ExtendedData and name/description.
KML coordinates are always WGS84 lon,lat[,alt] (EPSG:4326) per the OGC spec.
"""
from typing import Any

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from shapely.geometry import (
    GeometryCollection, LinearRing, LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon,
)
from shapely.geometry.base import BaseGeometry
from xml.etree.ElementTree import Element, ParseError

from app.errors import GeospatialFileError
from app.services.crs import WGS84
from app.services.readers.base import RawFeature, ReadResult
from app.services.readers.properties import sanitize

SIMPLE_GEOMETRIES = {"Point", "LineString", "LinearRing", "Polygon"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(el: Element, name: str) -> list[Element]:
    return [c for c in el if _local(c.tag) == name]


def _child(el: Element, name: str) -> Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el: Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t or None


def parse_coordinates(text: str | None) -> list[tuple[float, ...]]:
    if not text or not text.strip():
        raise ValueError("empty <coordinates>")
    coords: list[tuple[float, ...]] = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) not in (2, 3):
            raise ValueError(f"malformed coordinate tuple '{token}'")
        vals = tuple(float(p) for p in parts)
        lon, lat = vals[0], vals[1]
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError(f"coordinate out of range: lon={lon}, lat={lat}")
        coords.append(vals)
    return coords


def _ring(el: Element | None) -> list[tuple[float, ...]]:
    lr = _child(el, "LinearRing") if el is not None else None
    if lr is None:
        raise ValueError("polygon boundary without <LinearRing>")
    return parse_coordinates(_text(_child(lr, "coordinates")))


def _parse_geometry(el: Element) -> BaseGeometry | None:
    """Return a shapely geometry for a KML geometry element; None if the type is unsupported."""
    name = _local(el.tag)
    if name == "Point":
        return Point(parse_coordinates(_text(_child(el, "coordinates")))[0])
    if name == "LineString":
        return LineString(parse_coordinates(_text(_child(el, "coordinates"))))
    if name == "LinearRing":
        return LinearRing(parse_coordinates(_text(_child(el, "coordinates"))))
    if name == "Polygon":
        outer = _ring(_child(el, "outerBoundaryIs"))
        holes = [_ring(b) for b in _children(el, "innerBoundaryIs")]
        return Polygon(outer, holes)
    if name == "MultiGeometry":
        parts: list[BaseGeometry] = []
        for child in el:
            if _local(child.tag) in SIMPLE_GEOMETRIES | {"MultiGeometry"}:
                g = _parse_geometry(child)
                if g is not None:
                    parts.extend(g.geoms if g.geom_type.startswith("Multi") or g.geom_type == "GeometryCollection" else [g])
        if not parts:
            return None
        kinds = {p.geom_type for p in parts}
        if kinds == {"Point"}:
            return MultiPoint(parts)
        if kinds <= {"LineString", "LinearRing"}:
            return MultiLineString([LineString(p.coords) for p in parts])
        if kinds == {"Polygon"}:
            return MultiPolygon(parts)
        return GeometryCollection(parts)
    return None  # gx:Track, Model, etc.


def _extended_data(pm: Element) -> dict[str, Any]:
    props: dict[str, Any] = {}
    ext = _child(pm, "ExtendedData")
    if ext is None:
        return props
    for data in ext.iter():
        tag = _local(data.tag)
        if tag == "Data" and data.get("name"):
            props[data.get("name")] = _text(_child(data, "value"))
        elif tag == "SimpleData" and data.get("name"):
            props[data.get("name")] = _text(data)
    return props


GEOMETRY_TAGS = SIMPLE_GEOMETRIES | {"MultiGeometry", "Track", "MultiTrack", "Model"}


def read_kml_bytes(data: bytes, file_type: str = "kml") -> ReadResult:
    try:
        root = SafeET.fromstring(data)
    except (ParseError, DefusedXmlException, ValueError) as exc:
        raise GeospatialFileError(f"Invalid KML/XML document: {exc}") from exc
    if _local(root.tag) != "kml" and not any(_local(e.tag) == "Placemark" for e in root.iter()):
        raise GeospatialFileError("Document is not KML (no <kml> root or Placemark elements found).")

    result = ReadResult(file_type=file_type)

    def walk(el: Element, folder: str | None) -> None:
        for child in el:
            tag = _local(child.tag)
            if tag in ("Document", "Folder"):
                walk(child, _text(_child(child, "name")) or folder)
            elif tag == "Placemark":
                result.features.append(_placemark(child, folder))

    walk(root, None)
    if not result.features:  # root itself may be a Placemark container with odd nesting
        for pm in root.iter():
            if _local(pm.tag) == "Placemark":
                result.features.append(_placemark(pm, None))
    return result


def _placemark(pm: Element, folder: str | None) -> RawFeature:
    props: dict[str, Any] = {}
    if (n := _text(_child(pm, "name"))) is not None:
        props["name"] = n
    if (d := _text(_child(pm, "description"))) is not None:
        props["description"] = d
    props.update(_extended_data(pm))
    props = sanitize(props)

    geom_el = next((c for c in pm if _local(c.tag) in GEOMETRY_TAGS), None)
    if geom_el is None:
        return RawFeature(folder, None, WGS84, props)
    try:
        geom = _parse_geometry(geom_el)
    except Exception as exc:  # bad coordinates, degenerate rings, ...
        return RawFeature(folder, None, WGS84, props, error=f"Invalid {_local(geom_el.tag)} geometry: {exc}")
    if geom is None:
        return RawFeature(
            folder, None, WGS84, props,
            unsupported_reason=f"KML geometry '{_local(geom_el.tag)}' is not supported.",
        )
    return RawFeature(folder, geom, WGS84, props)
