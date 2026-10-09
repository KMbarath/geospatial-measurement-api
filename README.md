# Geospatial File Measurement API

A FastAPI backend that accepts a **Shapefile (`.zip`)** or **KML (`.kml`)**, extracts every feature
(index, geometry type, geometry, CRS, attributes) and returns **area** (polygons) and **length**
(lines), computed in a suitable **projected CRS — never on raw lat/lon degrees**.

* Python 3.12 · FastAPI · SQLAlchemy 2 (SQLite) · Shapely 2 · PyProj · pyshp
* 39 automated tests, including accuracy checks against an independent geodesic calculation
* Interactive docs at `/docs` (Swagger) once running

---

## 1. Setup

### Local

```bash
git clone <repo-url> && cd geospatial-measurement-api
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs>. A SQLite DB and uploaded files are created under `./data/`.

### Docker

```bash
docker compose up --build        # API on http://localhost:8000
```

### Tests

```bash
pytest -q
```

### Try it with the bundled samples

```bash
curl -F "file=@samples/survey.kml"         http://localhost:8000/api/files/
curl -F "file=@samples/plot_utm43n.zip"    http://localhost:8000/api/files/
curl -F "file=@samples/parcels_wgs84.zip"  http://localhost:8000/api/files/
python scripts/generate_samples.py          # regenerate the samples
```

### Configuration (env vars / `.env`, prefix `GEO_`)

| Variable | Default | Meaning |
|---|---|---|
| `GEO_DATABASE_URL` | `sqlite:///./data/app.db` | Any SQLAlchemy URL |
| `GEO_STORAGE_DIR` | `./data/uploads` | Where uploads are kept |
| `GEO_MAX_UPLOAD_MB` | `50` | Upload size limit (413 above) |
| `GEO_MAX_UNCOMPRESSED_MB` | `500` | Zip-bomb guard |
| `GEO_MAX_FEATURES` | `200000` | Feature-count guard |

---

## 2. API

All endpoints are under `/api/files/`. Interactive reference: `/docs`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/files/` | Upload + process a `.zip` (Shapefile) or `.kml` (multipart field `file`) |
| GET | `/api/files/{id}/` | File info / processing status |
| GET | `/api/files/{id}/measurements/` | Per-feature measurements + summary |
| GET | `/api/files/{id}/features/` | Features with geometry (GeoJSON), CRS, properties |
| GET | `/api/files/` | List uploads |
| DELETE | `/api/files/{id}/` | Delete a file, its features and stored upload |
| GET | `/health` | Liveness probe |

### `POST /api/files/`

```bash
curl -F "file=@samples/survey.kml" http://localhost:8000/api/files/
```

`201 Created`
```json
{
  "id": "c81daa12dcb746c094d42234160129b3",
  "filename": "survey.kml",
  "file_type": "kml",
  "size_bytes": 1268,
  "feature_count": 5,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error_message": null,
  "warnings": [],
  "created_at": "2026-10-09T04:30:02.752602Z",
  "processed_at": "2026-10-09T04:30:02.762659Z"
}
```

| Code | When |
|---|---|
| 201 | Processed (`status: COMPLETED`; per-feature problems do **not** fail the file) |
| 413 | Over the upload size limit |
| 415 | Extension is not `.zip` / `.kml` / `.kmz` |
| 422 | Accepted but unreadable (corrupt zip, no `.shp`, malformed KML …). The record is kept with `status: FAILED`; the body carries `id`, `error_message` and `detail` |

### `GET /api/files/{id}/`

```json
{ "id": "c81d…", "filename": "survey.kml", "feature_count": 5,
  "crs": "EPSG:4326", "status": "COMPLETED", "…": "…" }
```
`status` ∈ `PENDING | PROCESSING | COMPLETED | FAILED`. `crs` is the file's CRS, `MIXED` if layers differ, or `UNKNOWN`.
`404` if the id does not exist.

### `GET /api/files/{id}/measurements/`

Query params: `limit` (default 1000, max 10000), `offset`, `geometry_type`, `measurement_status`, `layer`.
`409` if the file is not `COMPLETED`.

```json
{
  "file_id": "c81d…",
  "filename": "survey.kml",
  "crs": "EPSG:4326",
  "summary": {
    "feature_count": 5,
    "by_geometry_type": {"GeometryCollection": 1, "LineString": 1, "Point": 1, "Polygon": 2},
    "by_measurement_status": {"MEASURED": 3, "NOT_APPLICABLE": 1, "UNSUPPORTED": 1},
    "total_area_sq_m": 5809312.4405, "total_area_hectares": 580.931244,
    "total_length_m": 4045.5255,     "total_length_km": 4.045526
  },
  "total": 5, "limit": 1000, "offset": 0,
  "results": [
    {
      "feature_id": 0, "layer": "Bengaluru survey", "geometry_type": "Polygon", "crs": "EPSG:4326",
      "measurement_status": "MEASURED",
      "area_sq_m": 1200289.838, "area_hectares": 120.028984, "area_sq_km": 1.20028984,
      "length_m": null, "length_km": null,
      "measurement_crs": "+proj=laea +lat_0=12.975000 +lon_0=77.595000 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs",
      "measurement_method": "azimuthal_equal_area",
      "measurement_note": null
    },
    {
      "feature_id": 2, "geometry_type": "LineString", "measurement_status": "MEASURED",
      "length_m": 4045.5255, "length_km": 4.045526,
      "measurement_crs": "EPSG:32643", "measurement_method": "utm", "…": "…"
    },
    { "feature_id": 3, "geometry_type": "Point", "measurement_status": "NOT_APPLICABLE",
      "measurement_note": "No measurement is defined for points.", "…": "…" },
    { "feature_id": 4, "geometry_type": "GeometryCollection", "measurement_status": "UNSUPPORTED",
      "measurement_note": "Measurement is not supported for geometry type 'GeometryCollection'.", "…": "…" }
  ]
}
```

`measurement_status`:

| Value | Meaning |
|---|---|
| `MEASURED` | Area (polygons) or length (lines) computed |
| `NOT_APPLICABLE` | Points — nothing to measure |
| `UNSUPPORTED` | No geometry, empty geometry, `GeometryCollection`, KML `gx:Track`, … (reason in `measurement_note`) |
| `FAILED` | Attempted but impossible: unknown CRS, un-transformable/out-of-range coordinates, bad geometry |

### `GET /api/files/{id}/features/`

Same filters/pagination (default `limit=100`). Geometry is GeoJSON **in the feature's source CRS**.

```json
{ "file_id": "c81d…", "total": 5, "limit": 100, "offset": 0,
  "results": [{
    "feature_id": 0, "layer": "Bengaluru survey", "geometry_type": "Polygon", "crs": "EPSG:4326",
    "geometry": {"type": "Polygon", "coordinates": [[[77.59, 12.97], "…"]]},
    "properties": {"name": "Parcel A", "owner": "Asha"},
    "measurement_status": "MEASURED", "area_sq_m": 1200289.838, "…": "…" }] }
```

---

## 3. Architecture

```
app/
├── main.py              app factory, lifespan (creates tables), /health
├── config.py            env-driven settings
├── database.py          engine / session helpers
├── models.py            UploadedFile 1──* Feature
├── schemas.py           response models (+ derived ha / km fields)
├── errors.py            domain exceptions
├── api/files.py         HTTP layer only: validation, status codes, pagination, filters
└── services/
    ├── storage.py       streamed, size-capped, sanitised disk writes
    ├── readers/
    │   ├── __init__.py  extension + archive-content dispatch, zip-bomb guards
    │   ├── shapefile.py pyshp → shapely, .prj → pyproj CRS
    │   ├── kml.py       defusedxml parser → shapely (WGS84)
    │   └── properties.py JSON-safe attribute values
    ├── crs.py           CRS labelling + choice of projected CRS
    ├── measurement.py   area / length, never raises
    └── processor.py     orchestration + status lifecycle
```

**File-processing flow**

1. `POST /api/files/` — extension check (415) → stream to `data/uploads/<id>/` with a size cap (413) → `PENDING` row.
2. `PROCESSING` → reader chosen from the extension and archive contents:
   * `.kml` → KML reader; `.zip` with `.shp` → Shapefile reader; a `.zip`/`.kmz` holding only a `.kml` → KML reader.
   * Zip members are grouped by layer stem and copied to a temp dir under *generated* names (zip-slip safe); `..`/absolute paths, `__MACOSX` and dotfiles are skipped; entry-count and uncompressed-size limits apply.
3. Each record becomes a `RawFeature` (geometry, CRS, attributes). A bad record yields a feature with an `error` rather than aborting the file.
4. Every feature is measured; features and their measurements are bulk-inserted in one transaction; file becomes `COMPLETED` (or `FAILED` with `error_message` if the file itself is unreadable).

**Measurement flow** (`services/measurement.py`)

`None`/empty → `UNSUPPORTED` · `Point`/`MultiPoint` → `NOT_APPLICABLE` · other non-line/polygon types → `UNSUPPORTED` · no CRS → `FAILED` ·
otherwise: drop Z → transform to WGS84 → validate lon/lat range → project → `.area` / `.length` → round to 4 decimals. `Multi*` geometries are summed. Invalid polygons are still measured and flagged in `measurement_note`. Everything is wrapped so one bad feature can never crash a request.

**CRS handling** (`services/crs.py`)

* Source CRS comes from the `.prj` (parsed by PyProj; labelled `EPSG:xxxx` when identifiable) or is WGS84 for KML (per spec). Each feature stores its CRS label.
* Geometry is stored and returned **in the source CRS**; measurements use a per-feature projected CRS:
  * **Area → custom Lambert Azimuthal Equal-Area** centred on the feature's bbox centre. Equal-area by construction, accurate for any size or latitude.
  * **Length → UTM zone** of the feature's centre (UPS beyond 84°N / 80°S). Standard conformal choice, scale error ≲ 0.1 %.
* The CRS used is reported per feature (`measurement_crs`, `measurement_method`).
* Missing `.prj`: if coordinates fit within lon/lat bounds, EPSG:4326 is assumed (with a warning); otherwise the CRS is `UNKNOWN` and features are `FAILED` rather than measured wrongly.

---

## 4. Design decisions

| Decision | Why | Alternatives considered |
|---|---|---|
| **FastAPI** | Typed models, automatic OpenAPI, light | Django + DRF (heavier; admin/ORM not needed) |
| **pyshp + custom KML parser** instead of GeoPandas/Fiona/GDAL | Pure-Python wheels → `pip install` works everywhere, small Docker image, no GDAL system libs; full control over error handling | GeoPandas/pyogrio (more formats, but heavy install; KML driver availability varies by wheel) |
| **Per-feature LAEA for area, UTM for length** | Always valid worldwide without a lookup table; equal-area guarantees correct area; UTM is the familiar standard for distance | One UTM zone per file (fails for large/multi-zone files); Web Mercator (badly wrong area at high latitude); a single global equal-area CRS (poor for distance) |
| **Projected measurement as required, geodesic as the test oracle** | The brief asks for projection; PyProj `Geod` (ellipsoidal) is an independent check, and tests assert agreement within 0.1 % | Geodesic in production (more exact for huge features; planned as an option) |
| **Synchronous processing** with a real status lifecycle | Simple and correct for typical survey files; response already contains the final result | Celery/RQ background jobs (see future scope) — the `PENDING → PROCESSING → COMPLETED/FAILED` model is already async-ready |
| **SQLite + JSON columns** | Zero-setup; measurements stored at ingest so reads are cheap and filterable | PostGIS (best long-term; unnecessary for this scope), re-measuring on read |
| **Per-feature failure isolation** | One bad geometry must not lose the other 119 features | Fail the whole file |
| **422 + persisted `FAILED` record for unreadable files** | The caller gets an id and can `GET` the reason later | Not persisting failures |
| **Defensive input handling** | `defusedxml` (entity bombs), zip-slip-safe extraction, uncompressed-size and entry limits, streamed size-capped upload, sanitised filenames | Trusting uploads |
| **Multi-layer zips supported** | Real-world zips often hold several shapefiles; each feature records its `layer` | Reject multi-shapefile zips |

### Known limitations

* Features crossing the antimeridian (KML has no way to express them without >180° longitudes, which are rejected) and features spanning more than ~10° get a reduced-accuracy note.
* `GeometryCollection` is reported `UNSUPPORTED` (mixing areas and lengths is ambiguous).
* Only 2-D measurement: Z values are ignored (area/length are planimetric).
* A projection is built per feature (transformers are LRU-cached); very large files (100k+ features) would benefit from batching features by region and vectorising.

---

## 5. Learnings

* **Never trust "degrees" for area/length** – a 0.01°×0.01° box has an "area" of 0.0001 in raw coordinates but ≈0.7 km² in reality; this is covered by a dedicated test.
* **CRS choice is per-purpose**: equal-area projections are right for area, conformal ones for distance; there is no single best CRS.
* **Shapefiles are a *bundle*** of files, and `.prj`/`.shx`/`.cpg` can be missing or ESRI-flavoured WKT — identification has to be confidence-based and failures need to be explicit rather than silent.
* **KML is looser than it looks**: nested Folders, `MultiGeometry`, `gx:` extensions, 3-D coordinates, `ExtendedData` in two shapes — graceful degradation matters more than completeness.
* **Validating against an independent oracle** (PyProj `Geod`) caught more than hand-computed expectations would.
* Upload endpoints are an attack surface: zip-slip, zip bombs and XML entity bombs were worth designing in from the start.

## 6. Future scope

* Background processing (Celery/RQ/ARQ) with polling or webhooks for very large files; progress reporting.
* PostgreSQL/PostGIS: spatial indexes, bbox / intersects queries, storing geometries natively.
* More formats: GeoJSON, GeoPackage, KMZ with assets, File Geodatabase (via GDAL/pyogrio as an optional extra).
* Optional **geodesic** measurement mode (`?method=geodesic`) and side-by-side comparison with the projected value.
* Perimeter, centroid, bounding box and (for 3-D data) surface/slope measurements; unit selection (`?units=acres`).
* Handling `GeometryCollection` by measuring each member; geometry repair (`make_valid`) option.
* Authentication, per-user quotas, rate limiting; object storage (S3) for uploads; Alembic migrations.
* Reproject/export endpoints (`/features/?crs=EPSG:3857`, GeoJSON FeatureCollection download).
* Observability: structured logs, metrics, tracing; load testing with large files.
