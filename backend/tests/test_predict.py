from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.database import get_db
from backend.main import app
from backend.models import cnn_model
from backend.services import face_detect


class FakeSession:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    async def commit(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(cnn_model, "load_model_once", lambda: None)
    session = FakeSession()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as test_client:
            yield test_client, session
    finally:
        app.dependency_overrides.clear()


def image_bytes(size=(64, 64), image_format="PNG"):
    output = BytesIO()
    Image.new("RGB", size, "white").save(output, format=image_format)
    return output.getvalue()


def upload(client, data, filename="face.png", content_type="image/png"):
    return client.post("/predict", files={"image": (filename, data, content_type)})


def test_rejects_no_face_without_saving_or_running_model(client, monkeypatch):
    test_client, session = client
    monkeypatch.setattr(face_detect, "_get_cascade", lambda: FakeCascade([]))
    response = upload(test_client, image_bytes())

    assert response.status_code == 400
    assert "No face found" in response.json()["detail"]
    assert session.records == []


class FakeCascade:
    def __init__(self, boxes):
        self.boxes = np.array(boxes, dtype=int).reshape(-1, 4)

    def detectMultiScale(self, gray, **kwargs):
        return self.boxes


def test_reports_the_largest_face_when_multiple_are_detected(client, monkeypatch):
    test_client, session = client
    monkeypatch.setattr(
        face_detect,
        "_get_cascade",
        lambda: FakeCascade([(1, 2, 10, 10), (12, 8, 30, 32)]),
    )

    class FakeModel:
        def predict(self, tensor, verbose=0):
            assert tensor.shape == (1, 48, 48, 1)
            return np.array([[0.1, 0.1, 0.6, 0.1, 0.1]])

    monkeypatch.setattr(cnn_model, "get_model", lambda: FakeModel())
    response = upload(test_client, image_bytes())

    assert response.status_code == 200
    assert response.json()["face_count"] == 2
    assert response.json()["face_box"] == {"x": 12, "y": 8, "width": 30, "height": 32}
    assert response.json()["image_width"] == 64
    assert response.json()["image_height"] == 64
    assert len(session.records) == 1


@pytest.mark.parametrize(
    ("data", "expected_status", "expected_detail"),
    [
        (b"", 400, "Empty image payload"),
        (b"x" * (5 * 1024 * 1024 + 1), 413, "5 MiB or smaller"),
        (image_bytes(image_format="GIF"), 400, "Supported formats"),
        (b"not an image", 400, "Unable to decode image"),
        (image_bytes(size=(4097, 1)), 400, "Image dimensions"),
    ],
)
def test_rejects_invalid_uploads(client, data, expected_status, expected_detail):
    test_client, session = client
    response = upload(test_client, data)

    assert response.status_code == expected_status
    assert expected_detail in response.json()["detail"]
    assert session.records == []
