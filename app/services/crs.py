"""CRS helpers: labelling source CRSs and choosing the *projected* CRS used for measuring.

Strategy
--------
Measurements are never done on lon/lat degrees. Every geometry is first brought to WGS84
(EPSG:4326) and then projected into a CRS chosen *per feature* from its location:

* **Area**   -> a custom Lambert Azimuthal Equal-Area (LAEA) projection centred on the
  feature's bounding-box centre. Equal-area means area is preserved by construction, for
  any location on Earth and any feature size.
* **Length** -> the UTM zone containing the feature's centre (UPS near the poles). UTM is
  conformal with a scale error <= ~0.1 % inside its zone, which is the industry-standard
  trade-off for distance.
"""
from dataclasses import dataclass
from functools import lru_cache

from pyproj import CRS, Transformer

WGS84 = CRS.from_epsg(4326)


@dataclass(frozen=True)
class ProjectedCRS:
    crs: CRS
    label: str       # human readable / reproducible identifier
    method: str      # "utm" | "ups" | "azimuthal_equal_area"


def crs_label(crs: CRS | None) -> str:
    """Return 'EPSG:xxxx' when the CRS can be identified confidently, else its name."""
    if crs is None:
        return "UNKNOWN"
    try:
        auth = crs.to_authority(min_confidence=70)
    except Exception:  # pragma: no cover - defensive
        auth = None
    if auth:
        return f"{auth[0]}:{auth[1]}"
    return crs.name or "UNKNOWN"


def is_wgs84(crs: CRS) -> bool:
    return crs.is_geographic and crs_label(crs) == "EPSG:4326"


def utm_crs(lon: float, lat: float) -> ProjectedCRS:
    """UTM zone for a lon/lat; polar stereographic (UPS) beyond 84N / 80S."""
    if lat > 84:
        return ProjectedCRS(CRS.from_epsg(32661), "EPSG:32661", "ups")
    if lat < -80:
        return ProjectedCRS(CRS.from_epsg(32761), "EPSG:32761", "ups")
    zone = min(60, max(1, int((lon + 180.0) // 6) + 1))
    epsg = (32600 if lat >= 0 else 32700) + zone
    return ProjectedCRS(CRS.from_epsg(epsg), f"EPSG:{epsg}", "utm")


def laea_crs(lon: float, lat: float) -> ProjectedCRS:
    """Equal-area projection centred on (lon, lat)."""
    proj = (
        f"+proj=laea +lat_0={lat:.6f} +lon_0={lon:.6f} "
        "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )
    return ProjectedCRS(CRS.from_proj4(proj), proj, "azimuthal_equal_area")


@lru_cache(maxsize=256)
def get_transformer(src: CRS, dst: CRS) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)
