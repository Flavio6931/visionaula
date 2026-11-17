"""Pruebas unitarias de la descarga/verificación de modelos y del comando descargar_modelos.

La red se simula: ninguna prueba descarga archivos reales.
"""

import hashlib
import io

import pytest
from django.core.management import CommandError, call_command

from vision import model_store
from vision.model_store import (
    MODELS,
    ModelSpec,
    ModelUnavailableError,
    download_model,
    is_model_valid,
    model_path,
    require_model,
    sha256_of,
)

pytestmark = pytest.mark.unit

CONTENIDO = b"modelo-onnx-de-prueba"


@pytest.fixture
def modelo_falso(monkeypatch):
    """Reemplaza la especificación de YuNet por una cuyo hash es el de CONTENIDO."""
    spec = ModelSpec(
        filename="modelo_prueba.onnx",
        url="https://ejemplo.invalid/modelo_prueba.onnx",
        sha256=hashlib.sha256(CONTENIDO).hexdigest(),
        description="Modelo de prueba",
    )
    monkeypatch.setitem(MODELS, "yunet", spec)
    return spec


def respuesta_http(contenido: bytes):
    """Simula urllib.request.urlopen devolviendo `contenido`."""

    def urlopen(url, timeout):
        assert timeout == model_store.DOWNLOAD_TIMEOUT_SECONDS
        return io.BytesIO(contenido)

    return urlopen


def test_sha256_of_matches_hashlib(tmp_path):
    archivo = tmp_path / "x.bin"
    archivo.write_bytes(CONTENIDO)
    assert sha256_of(archivo) == hashlib.sha256(CONTENIDO).hexdigest()


def test_download_installs_model_when_hash_matches(tmp_path, modelo_falso, monkeypatch):
    monkeypatch.setattr(model_store.urllib.request, "urlopen", respuesta_http(CONTENIDO))
    ruta = download_model(tmp_path, "yunet")
    assert ruta == tmp_path / modelo_falso.filename
    assert ruta.read_bytes() == CONTENIDO
    assert is_model_valid(tmp_path, "yunet")
    assert not ruta.with_suffix(".part").exists()  # no quedan temporales


def test_download_rejects_tampered_file_and_cleans_up(tmp_path, modelo_falso, monkeypatch):
    monkeypatch.setattr(model_store.urllib.request, "urlopen", respuesta_http(b"alterado"))
    with pytest.raises(ModelUnavailableError, match="SHA-256"):
        download_model(tmp_path, "yunet")
    assert list(tmp_path.iterdir()) == []  # ni modelo ni .part


def test_download_reports_network_errors(tmp_path, modelo_falso, monkeypatch):
    def sin_red(url, timeout):
        raise OSError("sin conexión")

    monkeypatch.setattr(model_store.urllib.request, "urlopen", sin_red)
    with pytest.raises(ModelUnavailableError, match="No se pudo descargar"):
        download_model(tmp_path, "yunet")
    assert list(tmp_path.iterdir()) == []


def test_corrupt_or_missing_model_is_not_valid(tmp_path, modelo_falso):
    assert not is_model_valid(tmp_path, "yunet")
    model_path(tmp_path, "yunet").write_bytes(b"corrupto")
    assert not is_model_valid(tmp_path, "yunet")


def test_require_model_returns_existing_path(tmp_path, modelo_falso):
    model_path(tmp_path, "yunet").write_bytes(CONTENIDO)
    assert require_model(tmp_path, "yunet") == tmp_path / modelo_falso.filename


# --- Comando de gestión ---------------------------------------------------


@pytest.fixture
def carpeta_modelos(settings, tmp_path):
    settings.VISION = {**settings.VISION, "MODELS_DIR": tmp_path}
    return tmp_path


def test_command_skips_models_already_installed(carpeta_modelos, monkeypatch):
    monkeypatch.setattr(
        "asistencia.management.commands.descargar_modelos.is_model_valid",
        lambda directorio, clave: True,
    )
    salida = io.StringIO()
    call_command("descargar_modelos", stdout=salida)
    assert salida.getvalue().count("ya está instalado") == len(MODELS)
    assert "Modelos listos" in salida.getvalue()


def test_command_downloads_missing_models(carpeta_modelos, monkeypatch):
    descargados = []

    def descargar(directorio, clave):
        descargados.append(clave)
        return directorio / f"{clave}.onnx"

    modulo = "asistencia.management.commands.descargar_modelos"
    monkeypatch.setattr(f"{modulo}.download_model", descargar)
    call_command("descargar_modelos", "--forzar", stdout=io.StringIO())
    assert descargados == list(MODELS)


def test_command_fails_with_clear_message(carpeta_modelos, monkeypatch):
    def falla(directorio, clave):
        raise ModelUnavailableError("No se pudo descargar: sin conexión")

    monkeypatch.setattr("asistencia.management.commands.descargar_modelos.download_model", falla)
    with pytest.raises(CommandError, match="sin conexión"):
        call_command("descargar_modelos", "--forzar", stdout=io.StringIO())
