"""Pruebas con las redes reales YuNet y SFace (se omiten si no están descargadas)."""

from pathlib import Path

import cv2
import numpy as np
import pytest
from django.conf import settings

from vision.detector import FaceDetector
from vision.model_store import (
    MODELS,
    ModelUnavailableError,
    is_model_valid,
    model_path,
    require_model,
)
from vision.pipeline import EnrollmentError, FaceEngine
from vision.recognizer import DEFAULT_THRESHOLD, EMPTY_GALLERY, FaceEmbedder

MODELS_DIR = settings.VISION["MODELS_DIR"]
MODELOS_PRESENTES = all(model_path(MODELS_DIR, k).is_file() for k in MODELS)

pytestmark = [
    pytest.mark.models,
    pytest.mark.skipif(not MODELOS_PRESENTES, reason="Ejecute manage.py descargar_modelos"),
]


@pytest.fixture(scope="module")
def engine():
    return FaceEngine.from_models(model_path(MODELS_DIR, "yunet"), model_path(MODELS_DIR, "sface"))


def test_downloaded_models_match_sha256():
    assert all(is_model_valid(MODELS_DIR, key) for key in MODELS)


def test_blank_frame_has_no_faces(engine):
    frame = np.full((480, 640, 3), 90, dtype=np.uint8)
    analysis = engine.analyze(frame, EMPTY_GALLERY)
    assert analysis.faces == ()
    assert analysis.elapsed_ms >= 0


def test_enrollment_without_face_is_rejected(engine):
    with pytest.raises(EnrollmentError, match="ningún rostro"):
        engine.enrollment_sample(np.full((480, 640, 3), 200, dtype=np.uint8))


def test_sface_produces_normalized_128d_embedding(detection):
    embedder = FaceEmbedder(model_path(MODELS_DIR, "sface"))
    rng = np.random.default_rng(7)
    image = rng.integers(0, 255, size=(240, 320, 3), dtype=np.uint8)
    vector = embedder.embed(image, detection)
    assert vector.shape == (128,)
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-4)


def test_require_model_reports_missing_file(tmp_path):
    with pytest.raises(ModelUnavailableError, match="descargar_modelos"):
        require_model(tmp_path, "yunet")


# --- Detector YuNet y reconocedor SFace con rostros reales -------------------

FIXTURES = Path(__file__).parent / "fixtures" / "rostros"


@pytest.fixture(scope="module")
def retratos():
    return {
        nombre: cv2.imread(str(FIXTURES / f"{nombre}.jpg")) for nombre in ("armstrong", "aldrin")
    }


@pytest.fixture(scope="module")
def detector():
    return FaceDetector(model_path(MODELS_DIR, "yunet"))


def test_yunet_detects_single_face_with_five_landmarks(detector, retratos):
    caras = detector.detect(retratos["armstrong"])
    assert len(caras) == 1
    cara = caras[0]
    assert cara.score >= 0.8
    assert len(cara.landmarks) == 5
    x, y, w, h = cara.box
    alto, ancho = retratos["armstrong"].shape[:2]
    assert 0 <= x < x + w <= ancho and 0 <= y < y + h <= alto
    ojo_der, ojo_izq, nariz = cara.landmarks[:3]
    assert ojo_der[1] < nariz[1] and ojo_izq[1] < nariz[1]  # los ojos están sobre la nariz


def test_yunet_sorts_faces_from_largest_to_smallest(detector, retratos):
    pequeno = cv2.resize(retratos["aldrin"], None, fx=0.5, fy=0.5)
    lienzo = np.zeros_like(retratos["armstrong"])
    lienzo[: pequeno.shape[0], : pequeno.shape[1]] = pequeno
    caras = detector.detect(np.hstack([lienzo, retratos["armstrong"]]))
    assert len(caras) == 2
    assert caras[0].area > caras[1].area
    assert caras[0].box[0] >= lienzo.shape[1]  # la más grande es la de Armstrong (derecha)


def test_min_face_size_discards_distant_faces(retratos):
    estricto = FaceDetector(model_path(MODELS_DIR, "yunet"), min_face_size=400)
    assert estricto.detect(retratos["armstrong"]) == []


def test_sface_distinguishes_same_person_from_another(engine, retratos):
    armstrong = engine.enrollment_sample(retratos["armstrong"]).embedding
    espejo = engine.enrollment_sample(cv2.flip(retratos["armstrong"], 1)).embedding
    aldrin = engine.enrollment_sample(retratos["aldrin"]).embedding
    misma_persona = float(armstrong @ espejo)
    otra_persona = float(armstrong @ aldrin)
    assert misma_persona >= DEFAULT_THRESHOLD > otra_persona
