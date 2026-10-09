import math

import pytest
from pyproj import CRS
from shapely.geometry import LineString, Point, Polygon

from app.models import MeasurementStatus
from app.services import crs as c
from app.services.measurement import measure
from app.services.readers.kml import parse_coordinates, read_kml_bytes
from tests.factories import kml_doc, kml_polygon


@pytest.mark.parametrize("lon,lat,epsg", [
    (77.5, 12.9, 32643), (-122.4, 37.8, 32610), (151.2, -33.9, 32756), (-179.9, 0.0, 32601),
    (179.9, 10.0, 32660), (0.0, 85.0, 32661), (0.0, -85.0, 32761),
])
def test_utm_zone_selection(lon, lat, epsg):
    assert c.utm_crs(lon, lat).label == f"EPSG:{epsg}"


def test_crs_label():
    assert c.crs_label(CRS.from_epsg(4326)) == "EPSG:4326"
    assert c.crs_label(CRS.from_wkt(CRS.from_epsg(32643).to_wkt(version="WKT1_ESRI"))) == "EPSG:32643"
    assert c.crs_label(None) == "UNKNOWN"


def test_equal_area_projection_preserves_area_at_poles_and_equator():
    # 1x1 degree cell: compare against pyproj's geodesic area at very different latitudes
    from pyproj import Geod
    g = Geod(ellps="WGS84")
    for lat in (0.0, 45.0, 75.0):
        ring = Polygon([(10, lat), (11, lat), (11, lat + 1), (10, lat + 1)])
        expected = abs(g.geometry_area_perimeter(ring)[0])
        got = measure(ring, c.WGS84).area_sq_m
        assert abs(got - expected) / expected < 0.001


def test_measure_handles_3d_and_invalid_polygon():
    p3d = Polygon([(0, 0, 5), (0.1, 0, 9), (0.1, 0.1, 1), (0, 0.1, 0)])
    assert measure(p3d, c.WGS84).status is MeasurementStatus.MEASURED
    bowtie = Polygon([(0, 0), (0.1, 0.1), (0.1, 0), (0, 0.1)])
    m = measure(bowtie, c.WGS84)
    assert m.status is MeasurementStatus.MEASURED and "Invalid" in m.note


def test_measure_statuses():
    assert measure(Point(1, 1), c.WGS84).status is MeasurementStatus.NOT_APPLICABLE
    assert measure(None, c.WGS84).status is MeasurementStatus.UNSUPPORTED
    assert measure(Polygon(), c.WGS84).status is MeasurementStatus.UNSUPPORTED
    assert measure(LineString([(0, 0), (1, 1)]), None).status is MeasurementStatus.FAILED
    assert measure(LineString([(0, 0), (1, 1)]), c.WGS84, error="boom").note == "boom"
    # coordinates that are not lon/lat in a declared geographic CRS
    assert measure(LineString([(0, 0), (500, 500)]), c.WGS84).status is MeasurementStatus.FAILED


def test_wide_extent_note():
    m = measure(LineString([(0, 0), (40, 5)]), c.WGS84)
    assert m.status is MeasurementStatus.MEASURED and "reduced" in m.note


def test_parse_coordinates_validation():
    assert parse_coordinates("1,2 3,4,5") == [(1.0, 2.0), (3.0, 4.0, 5.0)]
    for bad in ("", "1", "a,b", "200,0", "0,91", "1,2,3,4"):
        with pytest.raises(ValueError):
            parse_coordinates(bad)


def test_kml_nested_folders_extended_data_and_namespaces():
    xml = kml_doc(
        "<Folder><name>Outer</name><Folder><name>Inner</name>"
        + kml_polygon("0,0 1,0 1,1 0,1 0,0",
                      extra="<ExtendedData><SchemaData><SimpleData name='code'>X1</SimpleData></SchemaData></ExtendedData>")
        + "</Folder></Folder>"
    )
    res = read_kml_bytes(xml)
    assert len(res.features) == 1
    f = res.features[0]
    assert f.layer == "Inner" and f.properties["code"] == "X1"
