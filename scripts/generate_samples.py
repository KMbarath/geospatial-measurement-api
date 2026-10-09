"""Generate sample input files in ./samples (run: python scripts/generate_samples.py)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.factories import (  # noqa: E402
    box, kml_doc, kml_line, kml_point, kml_polygon, make_shapefile_zip, polygon_geo,
)

out = ROOT / "samples"
out.mkdir(exist_ok=True)

(out / "survey.kml").write_bytes(kml_doc(
    kml_polygon("77.5900,12.9700 77.6000,12.9700 77.6000,12.9800 77.5900,12.9800 77.5900,12.9700",
                "Parcel A", extra="<ExtendedData><Data name='owner'><value>Asha</value></Data></ExtendedData>")
    + kml_polygon("77.60,12.97 77.62,12.97 77.62,12.99 77.60,12.99 77.60,12.97", "Parcel B (with pond)",
                  inner="77.608,12.978 77.608,12.982 77.612,12.982 77.612,12.978 77.608,12.978")
    + kml_line("77.5900,12.9700 77.6050,12.9750 77.6200,12.9900", "Access road")
    + kml_point("77.5950,12.9750", "Survey marker")
    + "<Placemark><name>Mixed</name><MultiGeometry><Point><coordinates>77.6,12.97</coordinates></Point>"
      "<LineString><coordinates>77.6,12.97 77.61,12.98</coordinates></LineString></MultiGeometry></Placemark>",
    name="Bengaluru survey",
))

(out / "parcels_wgs84.zip").write_bytes(make_shapefile_zip(
    [polygon_geo([[(72.80, 19.00), (72.80, 19.05), (72.85, 19.05), (72.85, 19.00), (72.80, 19.00)]])],
    shape_type=5, epsg=4326, fields=(("name", "C", 40), ("ward", "N", 10, 0)), records=[("Ward 7", 7)],
))

(out / "plot_utm43n.zip").write_bytes(make_shapefile_zip(
    [polygon_geo(box(500000, 1400000, 501000, 1401000))], shape_type=5, epsg=32643,
    records=[("1 km square",)],
))
print("samples written to", out)
