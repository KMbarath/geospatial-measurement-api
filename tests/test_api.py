import io
import zipfile

import pytest
from pyproj import Geod

from tests.factories import (
    box, kml_doc, kml_line, kml_point, kml_polygon, make_shapefile_zip, polygon_geo,
)

GEOD = Geod(ellps="WGS84")


def geodesic_area(ring):
    lons, lats = zip(*ring)
    return abs(GEOD.polygon_area_perimeter(lons, lats)[0])


def geodesic_length(coords):
    lons, lats = zip(*coords)
    return GEOD.line_length(lons, lats)


def rel_err(a, b):
    return abs(a - b) / b


# ------------------------------------------------------------------ KML

def test_kml_upload_extracts_and_measures_all_geometry_types(upload, client):
    ring = [(77.0, 12.0), (77.1, 12.0), (77.1, 12.1), (77.0, 12.1), (77.0, 12.0)]
    line = [(77.0, 12.0), (77.2, 12.1), (77.4, 12.0)]
    kml = kml_doc(
        kml_polygon(" ".join(f"{x},{y},0" for x, y in ring), "plot",
                    extra="<ExtendedData><Data name='owner'><value>Asha</value></Data></ExtendedData>")
        + kml_line(" ".join(f"{x},{y}" for x, y in line), "road")
        + kml_point("77.05,12.05", "gate")
    )
    r = upload("survey.kml", kml)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "survey.kml"
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"
    fid = body["id"]

    assert client.get(f"/api/files/{fid}/").json()["feature_count"] == 3

    m = client.get(f"/api/files/{fid}/measurements/").json()
    poly, road, gate = m["results"]
    assert poly["geometry_type"] == "Polygon" and poly["measurement_status"] == "MEASURED"
    assert rel_err(poly["area_sq_m"], geodesic_area(ring)) < 0.001
    assert poly["area_hectares"] == pytest.approx(poly["area_sq_m"] / 1e4, rel=1e-6)
    assert road["geometry_type"] == "LineString"
    assert rel_err(road["length_m"], geodesic_length(line)) < 0.001
    assert road["measurement_crs"] == "EPSG:32643"  # UTM 43N covers lon 77E
    assert gate["measurement_status"] == "NOT_APPLICABLE" and gate["area_sq_m"] is None
    assert m["summary"]["by_geometry_type"] == {"Polygon": 1, "LineString": 1, "Point": 1}

    feats = client.get(f"/api/files/{fid}/features/").json()["results"]
    assert feats[0]["properties"] == {"name": "plot", "owner": "Asha"}
    assert feats[0]["crs"] == "EPSG:4326"
    assert feats[0]["geometry"]["type"] == "Polygon"


def test_never_measures_in_degrees(upload, client):
    # A 0.01 x 0.01 degree box: "area in degrees" would be 0.0001; real area is ~1.2 km^2.
    kml = kml_doc(kml_polygon("10,50 10.01,50 10.01,50.01 10,50.01 10,50"))
    fid = upload("tiny.kml", kml).json()["id"]
    area = client.get(f"/api/files/{fid}/measurements/").json()["results"][0]["area_sq_m"]
    assert 700_000 < area < 800_000  # ~0.71 km^2 at 50N


def test_polygon_hole_is_subtracted(upload, client):
    outer = "0,0 0.2,0 0.2,0.2 0,0.2 0,0"
    inner = "0.05,0.05 0.05,0.15 0.15,0.15 0.15,0.05 0.05,0.05"
    fid = upload("hole.kml", kml_doc(kml_polygon(outer, inner=inner))).json()["id"]
    area = client.get(f"/api/files/{fid}/measurements/").json()["results"][0]["area_sq_m"]
    full = geodesic_area([(0, 0), (0.2, 0), (0.2, 0.2), (0, 0.2), (0, 0)])
    hole = geodesic_area([(0.05, 0.05), (0.05, 0.15), (0.15, 0.15), (0.15, 0.05), (0.05, 0.05)])
    assert rel_err(area, full - hole) < 0.001


def test_multigeometry_and_unsupported_cases_are_graceful(upload, client):
    mixed = ("<Placemark><name>mixed</name><MultiGeometry><Point><coordinates>1,1</coordinates></Point>"
             "<LineString><coordinates>1,1 1.1,1.1</coordinates></LineString></MultiGeometry></Placemark>")
    multi_poly = ("<Placemark><name>mp</name><MultiGeometry>"
                  "<Polygon><outerBoundaryIs><LinearRing><coordinates>0,0 0.1,0 0.1,0.1 0,0.1 0,0</coordinates></LinearRing></outerBoundaryIs></Polygon>"
                  "<Polygon><outerBoundaryIs><LinearRing><coordinates>1,1 1.1,1 1.1,1.1 1,1.1 1,1</coordinates></LinearRing></outerBoundaryIs></Polygon>"
                  "</MultiGeometry></Placemark>")
    track = "<Placemark><name>t</name><gx:Track xmlns:gx='http://www.google.com/kml/ext/2.2'/></Placemark>"
    nogeom = "<Placemark><name>empty</name></Placemark>"
    bad = "<Placemark><name>bad</name><Point><coordinates>999,999</coordinates></Point></Placemark>"
    fid = upload("odd.kml", kml_doc(mixed + multi_poly + track + nogeom + bad)).json()["id"]
    res = client.get(f"/api/files/{fid}/measurements/").json()["results"]
    assert [r["measurement_status"] for r in res] == ["UNSUPPORTED", "MEASURED", "UNSUPPORTED", "UNSUPPORTED", "FAILED"]
    assert res[0]["geometry_type"] == "GeometryCollection"
    assert res[1]["geometry_type"] == "MultiPolygon"
    one_cell = geodesic_area([(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1), (0, 0)])
    two_cell = geodesic_area([(1, 1), (1.1, 1), (1.1, 1.1), (1, 1.1), (1, 1)])
    assert rel_err(res[1]["area_sq_m"], one_cell + two_cell) < 0.001
    assert all(r["measurement_note"] for r in (res[0], res[2], res[3], res[4]))


def test_multilinestring_length_is_summed(upload, client):
    xml = ("<Placemark><MultiGeometry><LineString><coordinates>10,10 10.1,10</coordinates></LineString>"
           "<LineString><coordinates>10,10.2 10.1,10.2</coordinates></LineString></MultiGeometry></Placemark>")
    fid = upload("ml.kml", kml_doc(xml)).json()["id"]
    r = client.get(f"/api/files/{fid}/measurements/").json()["results"][0]
    expected = geodesic_length([(10, 10), (10.1, 10)]) + geodesic_length([(10, 10.2), (10.1, 10.2)])
    assert r["geometry_type"] == "MultiLineString"
    assert rel_err(r["length_m"], expected) < 0.001


# ------------------------------------------------------------------ Shapefile

def test_shapefile_wgs84_polygons(upload, client):
    outer = [(72.8, 19.0), (72.8, 19.1), (72.9, 19.1), (72.9, 19.0), (72.8, 19.0)]  # clockwise
    data = make_shapefile_zip([polygon_geo([outer])], shape_type=5, epsg=4326, records=[("mumbai",)])
    r = upload("zones.zip", data)
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert r.json()["crs"] == "EPSG:4326" and r.json()["feature_count"] == 1
    m = client.get(f"/api/files/{fid}/measurements/").json()["results"][0]
    assert rel_err(m["area_sq_m"], geodesic_area(outer)) < 0.001
    f = client.get(f"/api/files/{fid}/features/").json()["results"][0]
    assert f["properties"] == {"name": "mumbai"} and f["layer"] == "layer"


def test_shapefile_projected_crs_is_handled(upload, client):
    # 1 km x 1 km square in UTM 43N (EPSG:32643)
    data = make_shapefile_zip([polygon_geo(box(500000, 1400000, 501000, 1401000))], shape_type=5, epsg=32643)
    r = upload("utm.zip", data)
    assert r.status_code == 201, r.text
    assert r.json()["crs"] == "EPSG:32643"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["results"][0]
    assert rel_err(m["area_sq_m"], 1_000_000) < 0.002


def test_shapefile_polylines_and_points(upload, client):
    line = [(80.0, 13.0), (80.1, 13.05), (80.2, 13.0)]
    data = make_shapefile_zip([{"type": "LineString", "coordinates": line}], shape_type=3, epsg=4326)
    fid = upload("roads.zip", data).json()["id"]
    m = client.get(f"/api/files/{fid}/measurements/").json()["results"][0]
    assert rel_err(m["length_m"], geodesic_length(line)) < 0.001

    pts = make_shapefile_zip([{"type": "Point", "coordinates": [80.0, 13.0]}], shape_type=1, epsg=4326)
    fid = upload("pts.zip", pts).json()["id"]
    m = client.get(f"/api/files/{fid}/measurements/").json()
    assert m["results"][0]["measurement_status"] == "NOT_APPLICABLE"
    assert m["summary"]["total_area_sq_m"] == 0


def test_shapefile_null_shape_is_handled(upload, client):
    data = make_shapefile_zip([None, {"type": "Point", "coordinates": [1, 1]}], shape_type=1, epsg=4326,
                              records=[("a",), ("b",)])
    fid = upload("n.zip", data).json()["id"]
    res = client.get(f"/api/files/{fid}/measurements/").json()["results"]
    assert res[0]["measurement_status"] == "UNSUPPORTED" and res[0]["geometry_type"] is None
    assert res[1]["measurement_status"] == "NOT_APPLICABLE"


def test_missing_prj_assumes_wgs84_when_coords_look_geographic(upload, client):
    data = make_shapefile_zip([polygon_geo(box(10, 50, 10.01, 50.01))], shape_type=5, epsg=None)
    r = upload("noprj.zip", data)
    assert r.status_code == 201
    assert r.json()["crs"] == "EPSG:4326"
    assert any("assumed" in w for w in r.json()["warnings"])
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["results"][0]
    assert m["measurement_status"] == "MEASURED"


def test_missing_prj_with_projected_coords_is_not_measured(upload, client):
    data = make_shapefile_zip([polygon_geo(box(500000, 1400000, 501000, 1401000))], shape_type=5, epsg=None)
    r = upload("mystery.zip", data)
    assert r.status_code == 201
    assert r.json()["crs"] == "UNKNOWN"
    m = client.get(f"/api/files/{r.json()['id']}/measurements/").json()["results"][0]
    assert m["measurement_status"] == "FAILED" and "CRS" in m["measurement_note"]


def test_missing_optional_parts_warn_but_work(upload):
    data = make_shapefile_zip([polygon_geo(box(10, 50, 10.01, 50.01))], shape_type=5, with_shx=False)
    r = upload("partial.zip", data)
    assert r.status_code == 201, r.text
    assert any(".shx missing" in w for w in r.json()["warnings"])


def test_multiple_layers_in_one_zip(upload, client):
    a = make_shapefile_zip([polygon_geo(box(10, 50, 10.01, 50.01))], shape_type=5, stem="a/parcels")
    b = make_shapefile_zip([{"type": "Point", "coordinates": [1, 1]}], shape_type=1, stem="b/wells", epsg=4326)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for blob in (a, b):
            with zipfile.ZipFile(io.BytesIO(blob)) as src:
                for n in src.namelist():
                    out.writestr(n, src.read(n))
    fid = upload("multi.zip", buf.getvalue()).json()["id"]
    res = client.get(f"/api/files/{fid}/measurements/?layer=wells").json()
    assert res["total"] == 1 and res["results"][0]["layer"] == "wells"
    assert client.get(f"/api/files/{fid}/").json()["feature_count"] == 2


def test_zip_slip_entries_are_ignored(upload):
    base = make_shapefile_zip([polygon_geo(box(10, 50, 10.01, 50.01))], shape_type=5,
                              extra_files={"../evil.shp": b"x", "/abs/evil.shp": b"y"})
    r = upload("slip.zip", base)
    assert r.status_code == 201 and r.json()["feature_count"] == 1


def test_kmz_style_zip_is_accepted(upload):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.kml", kml_doc(kml_point("1,1")))
    r = upload("tour.zip", buf.getvalue())
    assert r.status_code == 201 and r.json()["file_type"] == "kmz"


# ------------------------------------------------------------------ Errors & edge cases

def test_unsupported_extension_is_415(upload):
    assert upload("notes.txt", b"hello").status_code == 415
    assert upload("data.geojson", b"{}").status_code == 415


def test_corrupt_zip_marks_file_failed(upload, client):
    r = upload("bad.zip", b"this is not a zip")
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == "FAILED" and body["detail"]
    info = client.get(f"/api/files/{body['id']}/").json()
    assert info["status"] == "FAILED" and info["error_message"]
    assert client.get(f"/api/files/{body['id']}/measurements/").status_code == 409


def test_zip_without_geodata_is_422(upload):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "nothing here")
    assert upload("empty.zip", buf.getvalue()).status_code == 422


def test_malformed_kml_is_422(upload):
    assert upload("broken.kml", b"<kml><Placemark>").status_code == 422
    assert upload("html.kml", b"<html><body/></html>").status_code == 422


def test_xml_entity_bomb_is_rejected(upload):
    bomb = (b'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
            b'<kml><Document><Placemark><name>&b;</name></Placemark></Document></kml>')
    assert upload("bomb.kml", bomb).status_code == 422


def test_oversized_upload_is_413(upload):
    assert upload("big.kml", b"x" * (2 * 1024 * 1024)).status_code == 413


def test_empty_kml_document_completes_with_warning(upload):
    r = upload("none.kml", kml_doc(""))
    assert r.status_code == 201 and r.json()["feature_count"] == 0
    assert any("no features" in w for w in r.json()["warnings"])


def test_unknown_file_is_404(client):
    for suffix in ("", "measurements/", "features/"):
        assert client.get(f"/api/files/nope/{suffix}").status_code == 404
    assert client.delete("/api/files/nope/").status_code == 404


def test_pagination_filters_and_delete(upload, client, settings):
    pms = "".join(kml_point(f"{i/10},0", f"p{i}") for i in range(5)) + kml_line("0,0 0.1,0")
    fid = upload("many.kml", kml_doc(pms)).json()["id"]
    page = client.get(f"/api/files/{fid}/measurements/?limit=2&offset=1").json()
    assert page["total"] == 6 and [r["feature_id"] for r in page["results"]] == [1, 2]
    only_lines = client.get(f"/api/files/{fid}/measurements/?geometry_type=linestring").json()
    assert only_lines["total"] == 1 and only_lines["summary"]["total_length_m"] > 0
    assert client.get(f"/api/files/{fid}/measurements/?limit=0").status_code == 422

    listing = client.get("/api/files/").json()
    assert listing["total"] == 1 and listing["results"][0]["id"] == fid

    assert client.delete(f"/api/files/{fid}/").status_code == 204
    assert client.get(f"/api/files/{fid}/").status_code == 404
    assert not (settings.storage_dir / fid).exists()


def test_health_and_openapi(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert "/api/files/" in client.get("/openapi.json").json()["paths"]


def test_browser_dashboard_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Geospatial Measurement API" in response.text
    assert 'id="upload-form"' in response.text
