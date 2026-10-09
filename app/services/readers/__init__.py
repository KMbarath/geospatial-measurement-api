"""Reader dispatch: chooses a reader from the file extension and archive contents."""
import zipfile
from pathlib import Path, PurePosixPath

from app.errors import GeospatialFileError, UnsupportedFileTypeError
from app.services.readers.base import ReadResult
from app.services.readers.kml import read_kml_bytes
from app.services.readers.shapefile import group_shapefile_members, read_shapefile_zip

ACCEPTED_EXTENSIONS = {".zip", ".kml", ".kmz"}


def validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ACCEPTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext or filename}'. Upload a .zip (Shapefile) or a .kml file."
        )
    return ext


def _check_archive(zf: zipfile.ZipFile, max_uncompressed: int, max_members: int) -> None:
    infos = zf.infolist()
    if len(infos) > max_members:
        raise GeospatialFileError(f"Archive has too many entries (> {max_members}).")
    if sum(i.file_size for i in infos) > max_uncompressed:
        raise GeospatialFileError("Archive expands beyond the allowed uncompressed size.")


def read_geospatial_file(
    path: Path, ext: str, *, max_uncompressed: int, max_members: int = 1000
) -> ReadResult:
    if ext == ".kml":
        return read_kml_bytes(path.read_bytes(), "kml")

    if not zipfile.is_zipfile(path):
        raise GeospatialFileError("File is not a valid zip archive.")
    try:
        with zipfile.ZipFile(path) as zf:
            _check_archive(zf, max_uncompressed, max_members)
            if group_shapefile_members(zf):
                return read_shapefile_zip(zf)

            # No shapefile: accept a KMZ-style archive (zip containing a .kml).
            kmls = [i for i in zf.infolist() if PurePosixPath(i.filename).suffix.lower() == ".kml"
                    and "__MACOSX" not in i.filename]
            if kmls:
                kmls.sort(key=lambda i: (PurePosixPath(i.filename).name.lower() != "doc.kml", i.filename))
                return read_kml_bytes(zf.read(kmls[0]), "kmz")
    except zipfile.BadZipFile as exc:
        raise GeospatialFileError(f"Corrupt zip archive: {exc}") from exc
    raise GeospatialFileError("Archive contains neither a Shapefile (.shp) nor a KML document.")
