"""Pruebas de extremo a extremo (E2E) en un navegador real.

Se levanta el servidor de Django (live_server) y se controla Google Chrome con
Playwright. Chrome recibe una CÁMARA SIMULADA: un video .y4m generado con los
retratos de Neil Armstrong (estudiante registrado) y Buzz Aldrin (no registrado).
Así se prueba el flujo completo que haría un docente, sin intervención humana:

    login -> panel -> estudiantes -> registro de rostro -> sesión -> monitor en vivo
    (detección, reconocimiento, asistencia, pixelado, filtros) -> reporte -> CSV

Cada paso guarda una captura en docs/pruebas/capturas/ como evidencia.

Requisitos: `pip install playwright` y Google Chrome instalado
(o `python -m playwright install chromium` y E2E_CHANNEL=chromium).
"""

import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from asistencia.models import Asistencia, Estudiante, MuestraRostro, SesionClase
from vision.model_store import MODELS, model_path

playwright_api = pytest.importorskip("playwright.sync_api")

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = RAIZ / "tests" / "fixtures" / "rostros"
CAPTURAS = RAIZ / "docs" / "pruebas" / "capturas"
MODELOS_PRESENTES = all(model_path(settings.VISION["MODELS_DIR"], k).is_file() for k in MODELS)
USUARIO, CLAVE = "docente_e2e", "Prueba-E2E-2026"
# El menú lateral tiene un botón "Cerrar sesión" (logout): se apunta siempre al formulario
# principal de la página para no pulsarlo por error.
ENVIAR = "main form button.btn-primary[type=submit]"
TIEMPO_MAX_MS = 30_000
VIEWPORT = {"width": 1366, "height": 860}

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(not MODELOS_PRESENTES, reason="Ejecute manage.py descargar_modelos"),
]


# --- Cámara simulada ----------------------------------------------------------


def escribir_y4m(destino: Path, imagen: np.ndarray, cuadros: int = 10) -> Path:
    """Guarda `imagen` como video YUV4MPEG2 (formato que Chrome acepta como cámara falsa)."""
    alto, ancho = imagen.shape[:2]
    yuv = cv2.cvtColor(imagen, cv2.COLOR_BGR2YUV_I420).tobytes()
    with open(destino, "wb") as video:
        video.write(f"YUV4MPEG2 W{ancho} H{alto} F10:1 Ip A1:1 C420jpeg\n".encode())
        for _ in range(cuadros):
            video.write(b"FRAME\n" + yuv)
    return destino


def escena_del_aula() -> np.ndarray:
    """Cuadro 1280x720 con los dos retratos uno al lado del otro."""
    retratos = [cv2.imread(str(FIXTURES / f"{n}.jpg")) for n in ("armstrong", "aldrin")]
    retratos = [cv2.resize(r, (576, 720), interpolation=cv2.INTER_AREA) for r in retratos]
    lienzo = np.full((720, 1280, 3), 25, dtype=np.uint8)
    lienzo[:, 64:640] = retratos[0]
    lienzo[:, 640:1216] = retratos[1]
    return lienzo


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture
def navegador(tmp_path_factory):
    canal = os.getenv("E2E_CHANNEL", "chrome")
    video = escribir_y4m(tmp_path_factory.mktemp("camara") / "aula.y4m", escena_del_aula())
    argumentos = [
        "--use-fake-ui-for-media-stream",  # concede el permiso de cámara sin preguntar
        "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-video-capture={video}",
    ]
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                channel=None if canal == "chromium" else canal,
                headless=os.getenv("E2E_HEADED") != "1",
                args=argumentos,
            )
        except playwright_api.Error as error:
            pytest.skip(f"No se pudo abrir el navegador '{canal}': {error.message[:120]}")
        yield browser
        browser.close()


@pytest.fixture
def pagina(navegador, live_server, settings, monkeypatch):
    # Playwright mantiene un bucle asyncio en este hilo; el ORM se usa solo para preparar datos.
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    settings.ROOT_URLCONF = "tests.urls_e2e"
    contexto = navegador.new_context(viewport=VIEWPORT, locale="es-EC", base_url=live_server.url)
    contexto.set_default_timeout(TIEMPO_MAX_MS)
    page = contexto.new_page()
    page.on("dialog", lambda dialogo: dialogo.accept())  # confirmación de "Cerrar sesión"
    yield page
    contexto.close()


@pytest.fixture
def datos_iniciales(db):
    get_user_model().objects.create_user(USUARIO, password=CLAVE, first_name="Docente")
    # Estudiante registrado SIN fotos: aparecerá como ausente en el reporte.
    Estudiante.objects.create(cedula="0912345675", nombres="Ana", apellidos="Pérez")


def capturar(page, nombre: str) -> None:
    CAPTURAS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(CAPTURAS / f"{nombre}.png"), full_page=True)


def iniciar_sesion(page) -> None:
    page.goto("/cuentas/login/")
    page.fill("input[name=username]", USUARIO)
    page.fill("input[name=password]", CLAVE)
    page.click("button[type=submit]")  # en el login no existe el menú lateral
    page.wait_for_url(lambda url: "/cuentas/login/" not in url)


# --- Pruebas ------------------------------------------------------------------


def test_e2e_rutas_protegidas_redirigen_al_login(pagina, datos_iniciales):
    pagina.goto("/monitor/")
    assert "/cuentas/login/" in pagina.url
    pagina.fill("input[name=username]", USUARIO)
    pagina.fill("input[name=password]", "clave-incorrecta")
    pagina.click("button[type=submit]")
    playwright_api.expect(pagina.locator(".alert-error")).to_contain_text("incorrectos")
    capturar(pagina, "01-login-error")


def test_e2e_flujo_completo_del_docente(pagina, datos_iniciales, tmp_path):
    expect = playwright_api.expect

    # 1. Inicio de sesión y panel de control.
    pagina.goto("/cuentas/login/")
    capturar(pagina, "02-login")
    iniciar_sesion(pagina)
    expect(pagina.locator("h1")).to_have_text("Panel de control")
    capturar(pagina, "03-panel")

    # 2. Registro de estudiante: primero con cédula inválida, luego válida.
    pagina.goto("/estudiantes/nuevo/")
    pagina.fill("input[name=cedula]", "0912345678")
    pagina.fill("input[name=nombres]", "Neil")
    pagina.fill("input[name=apellidos]", "Armstrong")
    pagina.click(ENVIAR)
    expect(pagina.locator("main form")).to_contain_text("dígito verificador no coincide")
    capturar(pagina, "04-cedula-invalida")
    pagina.fill("input[name=cedula]", "1710034065")
    pagina.click(ENVIAR)
    pagina.wait_for_url("**/rostro/")

    # 3. Registro del rostro: la cámara muestra a DOS personas -> debe rechazarse.
    pagina.click("#btn-camara")
    expect(pagina.locator("#btn-capturar")).to_be_enabled()
    pagina.click("#btn-capturar")
    expect(pagina.locator("#estado")).to_contain_text("más de un rostro")
    capturar(pagina, "05-registro-dos-rostros")
    pagina.click("#btn-camara")  # apagar cámara

    #    Se suben fotos individuales del estudiante (opción "Subir foto").
    armstrong = cv2.imread(str(FIXTURES / "armstrong.jpg"))
    fotos = []
    for i, variante in enumerate(
        (armstrong, cv2.flip(armstrong, 1), cv2.convertScaleAbs(armstrong, alpha=0.8))
    ):
        ruta = tmp_path / f"foto{i}.jpg"
        cv2.imwrite(str(ruta), variante)
        fotos.append(ruta)
    for total, foto in enumerate(fotos, start=1):
        pagina.set_input_files("#archivo", str(foto))
        expect(pagina.locator("#contador")).to_have_text(str(total))
    expect(pagina.locator("#estado")).to_contain_text("Foto registrada (3/")
    capturar(pagina, "06-registro-rostro")
    assert MuestraRostro.objects.filter(estudiante__cedula="1710034065").count() == 3

    pagina.goto("/estudiantes/")
    expect(pagina.locator("table")).to_contain_text("Armstrong")
    capturar(pagina, "07-estudiantes")

    # 4. Sesión de clase y monitor en vivo.
    pagina.goto("/sesiones/")
    pagina.fill("input[name=asignatura]", "Construcción de Software")
    pagina.fill("input[name=tema]", "Práctica 4 - Pruebas")
    pagina.click(ENVIAR)
    pagina.wait_for_url("**/monitor/?sesion=*")
    expect(pagina.locator(".badge-live")).to_have_text("EN CURSO")

    pagina.click("#btn-camara")
    expect(pagina.locator("#m-rostros")).to_have_text("2")  # detecta a los dos
    expect(pagina.locator("#m-desc")).to_have_text("1")  # Aldrin no está registrado
    expect(pagina.locator("#en-vivo")).to_contain_text("Neil Armstrong")
    expect(pagina.locator("#en-vivo")).to_contain_text("Desconocido")
    expect(pagina.locator("#registrados")).to_contain_text("Neil Armstrong")  # asistencia
    expect(pagina.locator("#resumen")).to_have_text("1/2")
    pixeles_dibujados = pagina.evaluate(
        """() => {
            const c = document.getElementById('overlay');
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) n++;
            return n;
        }"""
    )
    assert pixeles_dibujados > 1000  # marcos, nombres y pixelado sobre el video
    capturar(pagina, "08-monitor-reconocimiento")

    # 5. Filtro de OpenCV: el video vuelve procesado desde el servidor.
    pagina.select_option("#modo", "bordes")
    expect(pagina.locator("#salida")).to_be_visible()
    capturar(pagina, "09-monitor-filtro-bordes")
    pagina.select_option("#modo", "termico")
    pagina.wait_for_timeout(1500)
    capturar(pagina, "10-monitor-filtro-termico")
    pagina.click("#btn-camara")
    expect(pagina.locator("#estado")).to_have_text("Cámara detenida.")

    # 6. Reporte de la sesión, cierre y exportación CSV.
    sesion = SesionClase.objects.get()
    assert Asistencia.objects.filter(sesion=sesion).count() == 1  # sin duplicados
    pagina.goto(f"/sesiones/{sesion.pk}/")
    expect(pagina.locator(".stats")).to_contain_text("50,0%")  # formato es-EC
    capturar(pagina, "11-detalle-sesion")
    pagina.click(".actions button.btn-danger")  # cerrar la sesión de clase (no el logout)
    expect(pagina.locator(".actions button.btn-danger")).to_have_count(0)
    sesion.refresh_from_db()
    assert not sesion.activa

    with pagina.expect_download() as descarga:
        pagina.click("text=Exportar CSV")
    contenido = Path(descarga.value.path()).read_text(encoding="utf-8-sig")
    assert "1710034065,Armstrong,Neil,Presente" in contenido
    assert "0912345675,Pérez,Ana,Ausente" in contenido

    pagina.goto("/")
    capturar(pagina, "12-panel-final")
