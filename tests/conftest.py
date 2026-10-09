import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "uploads",
        max_upload_mb=1,
    )


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture()
def upload(client):
    def _upload(name: str, data: bytes, content_type: str = "application/octet-stream"):
        return client.post("/api/files/", files={"file": (name, data, content_type)})
    return _upload
