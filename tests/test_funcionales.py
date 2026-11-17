"""Pruebas funcionales (Sesión 2): casos de uso clave con las redes reales YuNet y SFace.

A diferencia de las pruebas de integración, aquí NO se simula el motor de visión:
cada fotograma pasa por el pipeline completo de OpenCV. Se usan dos retratos
oficiales de la NASA (dominio público) como "cámara":

- armstrong.jpg -> estudiante registrado (Neil Armstrong).
- aldrin.jpg    -> persona NO registrada (debe aparecer como desconocida y pixelada).

Casos de uso cubiertos:
    CU-01 Inicio: el docente inicia sesión y ve el panel.
    CU-02 Registro de estudiante y de su rostro.
    CU-03 Detección en video (secuencia de fotogramas, sin sesión de clase).
    CU-04 Toma de asistencia automática en una sesión de clase.
    CU-05 Visualización en la interfaz: filtros, privacidad y poca luz.
    CU-06 Cierre de la sesión y reporte (detalle y CSV).
"""

import base64
from pathlib import Path

import cv2
import numpy as np
import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from asistencia import services
from asistencia.models import Asistencia, Estudiante, MuestraRostro, SesionClase
from vision.model_store import MODELS, model_path

FIXTURES = Path(__file__).parent / "fixtures" / "rostros"
MODELOS_PRESENTES = all(model_path(settings.VISION["MODELS_DIR"], k).is_file() for k in MODELS)
CEDULA_ARMSTRONG = "1710034065"
CLAVE_DOCENTE = "Clave-Segura-123"

pytestmark = [
    pytest.mark.functional,
    pytest.mark.django_db,
    pytest.mark.skipif(not MODELOS_PRESENTES, reason="Ejecute manage.py descargar_modelos"),
]


# --- Utilidades -------------------------------------------------------------


def leer(nombre: str) -> np.ndarray:
    imagen = cv2.imread(str(FIXTURES / nombre))
    assert imagen is not None, f"Falta la imagen de prueba {nombre}"
    return imagen


def a_jpeg(imagen: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    return buffer.tobytes()


def archivo(imagen: np.ndarray) -> SimpleUploadedFile:
    return SimpleUploadedFile("frame.jpg", a_jpeg(imagen), content_type="image/jpeg")


def desde_data_url(data_url: str) -> np.ndarray:
    datos = base64.b64decode(data_url.split(",", 1)[1])
    return cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR)


def aula(*retratos: np.ndarray) -> np.ndarray:
    """Une varios retratos lado a lado, como si estuvieran frente a la misma cámara."""
    return np.hstack(retratos)


def fotogramas_de_video(imagen: np.ndarray, cantidad: int = 5) -> list:
    """Simula un video: la persona se desplaza un poco en cada fotograma."""
    alto, ancho = imagen.shape[:2]
    return [
        cv2.warpAffine(imagen, np.float32([[1, 0, 6 * i], [0, 1, 3 * i]]), (ancho, alto))
        for i in range(cantidad)
    ]


def procesar(cliente, fotograma, sesion=None, **extra) -> dict:
    datos = {"frame": archivo(fotograma), "sesion": sesion.pk if sesion else "", **extra}
    respuesta = cliente.post(reverse("asistencia:api_procesar"), datos)
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()["data"]


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def armstrong():
    return leer("armstrong.jpg")


@pytest.fixture
def aldrin():
    return leer("aldrin.jpg")


@pytest.fixture
def estudiante_enrolado(cliente, armstrong):
    """Estudiante registrado con 3 muestras reales (normal, espejo y algo más oscura)."""
    estudiante = Estudiante.objects.create(
        cedula=CEDULA_ARMSTRONG, nombres="Neil", apellidos="Armstrong", curso="Software 5A"
    )
    url = reverse("asistencia:api_muestra", args=[estudiante.pk])
    oscura = cv2.convertScaleAbs(armstrong, alpha=0.8)
    for foto in (armstrong, cv2.flip(armstrong, 1), oscura):
        assert cliente.post(url, {"frame": archivo(foto)}).status_code == 201
    return estudiante


# --- CU-01 Inicio -----------------------------------------------------------


def test_cu01_docente_inicia_sesion_y_ve_el_panel(client, docente):
    respuesta = client.post(
        reverse("login"), {"username": "docente", "password": CLAVE_DOCENTE}, follow=True
    )
    assert respuesta.redirect_chain[-1][0] == reverse("asistencia:dashboard")
    assert respuesta.context["modelos_listos"] is True
    assert "Panel" in respuesta.content.decode()


def test_cu01_credenciales_incorrectas_no_permiten_ingresar(client, docente):
    respuesta = client.post(reverse("login"), {"username": "docente", "password": "mala"})
    assert respuesta.status_code == 200
    assert "Usuario o contraseña incorrectos" in respuesta.content.decode()
    assert client.get(reverse("asistencia:dashboard")).status_code == 302


# --- CU-02 Registro de estudiante y de su rostro ---------------------------


def test_cu02_registrar_estudiante_y_sus_fotos(cliente, armstrong):
    respuesta = cliente.post(
        reverse("asistencia:estudiante_nuevo"),
        {"cedula": CEDULA_ARMSTRONG, "nombres": "neil", "apellidos": "armstrong", "activo": "on"},
    )
    estudiante = Estudiante.objects.get(cedula=CEDULA_ARMSTRONG)
    assert respuesta["Location"] == reverse("asistencia:estudiante_enrolar", args=[estudiante.pk])

    url = reverse("asistencia:api_muestra", args=[estudiante.pk])
    cuerpo = cliente.post(url, {"frame": archivo(armstrong)}).json()
    assert cuerpo["ok"] and cuerpo["data"]["total"] == 1
    assert cuerpo["data"]["calidad"] > 0.5
    muestra = MuestraRostro.objects.get()
    assert muestra.vector().shape == (128,)
    assert Path(muestra.imagen.path).is_file()


def test_cu02_rechaza_fotos_sin_rostro_o_con_dos_personas(cliente, armstrong, aldrin):
    estudiante = Estudiante.objects.create(
        cedula=CEDULA_ARMSTRONG, nombres="Neil", apellidos="Armstrong"
    )
    url = reverse("asistencia:api_muestra", args=[estudiante.pk])
    pared = np.full((480, 640, 3), 170, dtype=np.uint8)

    sin_rostro = cliente.post(url, {"frame": archivo(pared)})
    dos_personas = cliente.post(url, {"frame": archivo(aula(armstrong, aldrin))})

    assert sin_rostro.status_code == 422
    assert sin_rostro.json()["error"] == "No se detectó ningún rostro."
    assert dos_personas.status_code == 422
    assert "más de un rostro" in dos_personas.json()["error"]
    assert not MuestraRostro.objects.exists()


# --- CU-03 Detección en video ----------------------------------------------


def test_cu03_detecta_y_reconoce_en_cada_fotograma_del_video(
    cliente, estudiante_enrolado, armstrong
):
    for fotograma in fotogramas_de_video(armstrong):
        datos = procesar(cliente, fotograma, imagen="0")
        assert datos["total_rostros"] == 1
        rostro = datos["rostros"][0]
        assert rostro["nombre"] == "Neil Armstrong"
        assert rostro["similitud"] >= settings.VISION["MATCH_THRESHOLD"]
        assert len(rostro["puntos"]) == 5
    assert not Asistencia.objects.exists()  # sin sesión de clase no se registra


def test_cu03_galeria_vacia_avisa_que_no_hay_estudiantes(cliente, armstrong):
    datos = procesar(cliente, armstrong, imagen="0")
    assert datos["galeria_vacia"] is True
    assert datos["desconocidos"] == 1


# --- CU-04 Toma de asistencia ----------------------------------------------


def test_cu04_registra_asistencia_solo_del_estudiante_registrado(
    cliente, estudiante_enrolado, armstrong, aldrin
):
    respuesta = cliente.post(reverse("asistencia:sesiones"), {"asignatura": "Construcción"})
    sesion = SesionClase.objects.get()
    assert respuesta["Location"].endswith(f"?sesion={sesion.pk}")

    camara = aula(armstrong, aldrin)
    respuestas = [procesar(cliente, camara, sesion, imagen="0") for _ in range(4)]

    nuevas = [len(r["nuevas_asistencias"]) for r in respuestas]
    assert nuevas == [0, 0, 1, 0]  # se confirma al 3er fotograma y no se duplica
    assert all(r["total_rostros"] == 2 and r["desconocidos"] == 1 for r in respuestas)
    registro = respuestas[2]["nuevas_asistencias"][0]
    assert registro["estudiante"] == "Neil Armstrong"
    assert registro["cedula"] == CEDULA_ARMSTRONG
    asistencia = Asistencia.objects.get()
    assert asistencia.estudiante == estudiante_enrolado
    assert Path(asistencia.evidencia.path).is_file()


# --- CU-05 Visualización en la interfaz ------------------------------------


@pytest.mark.parametrize("modo", ["normal", "gris", "bordes", "termico", "clahe"])
def test_cu05_cada_filtro_devuelve_el_video_procesado(
    cliente, estudiante_enrolado, armstrong, modo
):
    datos = procesar(cliente, armstrong, modo=modo, imagen="1")
    salida = desde_data_url(datos["imagen"])
    assert salida.shape[:2] == (datos["alto"], datos["ancho"]) == armstrong.shape[:2]
    assert datos["rostros"][0]["nombre"] == "Neil Armstrong"


def test_cu05_el_rostro_no_registrado_se_pixela_y_el_registrado_no(
    cliente, estudiante_enrolado, armstrong, aldrin
):
    camara = aula(armstrong, aldrin)
    datos = procesar(cliente, camara, imagen="1")
    salida = desde_data_url(datos["imagen"])
    por_nombre = {r["nombre"]: r for r in datos["rostros"]}

    def detalle(imagen, caja):
        """Nitidez del centro del rostro: alta si se ve, baja si está pixelado."""
        x, y, w, h = caja
        centro = imagen[y + h // 4 : y + 3 * h // 4, x + w // 4 : x + 3 * w // 4]
        gris = cv2.cvtColor(centro, cv2.COLOR_BGR2GRAY)
        return cv2.Laplacian(gris, cv2.CV_64F).var()

    conocido, desconocido = por_nombre["Neil Armstrong"]["box"], por_nombre[None]["box"]
    assert detalle(salida, desconocido) < 0.3 * detalle(camara, desconocido)
    assert detalle(salida, conocido) > 0.5 * detalle(camara, conocido)


def test_cu05_con_poca_luz_aplica_clahe_y_sigue_reconociendo(
    cliente, estudiante_enrolado, armstrong
):
    oscura = cv2.convertScaleAbs(armstrong, alpha=0.35)
    datos = procesar(cliente, oscura, imagen="0")
    assert datos["poca_luz"] is True
    assert datos["rostros"][0]["nombre"] == "Neil Armstrong"


# --- CU-06 Cierre de la sesión y reporte -----------------------------------


def test_cu06_cerrar_sesion_y_obtener_reporte(cliente, docente, estudiante_enrolado, armstrong):
    Estudiante.objects.create(cedula="0912345675", nombres="Buzz", apellidos="Aldrin")
    sesion = services.abrir_sesion(SesionClase(asignatura="Construcción", docente=docente))
    for _ in range(3):
        procesar(cliente, armstrong, sesion, imagen="0")

    cliente.post(reverse("asistencia:sesion_cerrar", args=[sesion.pk]))
    sesion.refresh_from_db()
    assert not sesion.activa
    for _ in range(3):  # con la sesión cerrada ya no se registra nada nuevo
        procesar(cliente, armstrong, sesion, imagen="0")

    detalle = cliente.get(reverse("asistencia:sesion_detalle", args=[sesion.pk]))
    assert detalle.context["stats"] == {
        "inscritos": 2,
        "presentes": 1,
        "ausentes": 1,
        "porcentaje": 50.0,
    }
    csv = cliente.get(reverse("asistencia:sesion_csv", args=[sesion.pk]))
    filas = csv.content.decode("utf-8-sig").splitlines()
    assert filas[0].startswith("Cédula,Apellidos,Nombres,Estado")
    assert any(f.startswith(f"{CEDULA_ARMSTRONG},Armstrong,Neil,Presente") for f in filas)
    assert any(f.startswith("0912345675,Aldrin,Buzz,Ausente") for f in filas)
