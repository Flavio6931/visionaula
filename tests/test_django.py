"""Pruebas de integración: vistas, API, servicios y base de datos."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from asistencia import services
from asistencia.models import Asistencia, Estudiante, MuestraRostro, SesionClase
from vision.model_store import ModelUnavailableError

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def frame(data: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile("frame.jpg", data, content_type="image/jpeg")


def nueva_sesion(docente, **extra) -> SesionClase:
    return SesionClase.objects.create(
        asignatura="Construcción de Software", docente=docente, **extra
    )


# --- Autenticación --------------------------------------------------------


@pytest.mark.parametrize(
    "nombre",
    ["asistencia:dashboard", "asistencia:monitor", "asistencia:estudiantes", "asistencia:sesiones"],
)
def test_pages_require_login(client, nombre):
    response = client.get(reverse(nombre))
    assert response.status_code == 302 and "/cuentas/login/" in response["Location"]


def test_api_returns_401_json_when_not_logged_in(client, jpeg_bytes):
    response = client.post(reverse("asistencia:api_procesar"), {"frame": frame(jpeg_bytes)})
    assert response.status_code == 401
    assert response.json()["ok"] is False


def test_login_page_renders(client):
    assert client.get(reverse("login")).status_code == 200


# --- Páginas --------------------------------------------------------------


@pytest.mark.parametrize(
    "nombre",
    [
        "asistencia:dashboard",
        "asistencia:monitor",
        "asistencia:estudiantes",
        "asistencia:sesiones",
        "asistencia:estudiante_nuevo",
    ],
)
def test_pages_render_for_logged_user(cliente, nombre):
    assert cliente.get(reverse(nombre)).status_code == 200


def test_monitor_uses_active_session(cliente, docente):
    sesion = nueva_sesion(docente)
    response = cliente.get(reverse("asistencia:monitor"))
    assert response.context["sesion"] == sesion


# --- Estudiantes ----------------------------------------------------------


def test_create_student_normalizes_data_and_redirects_to_enrollment(cliente):
    response = cliente.post(
        reverse("asistencia:estudiante_nuevo"),
        {
            "cedula": " 171003406-5 ",
            "nombres": "  ana   maría ",
            "apellidos": "pérez",
            "activo": "on",
        },
    )
    estudiante = Estudiante.objects.get()
    assert estudiante.cedula == "1710034065"
    assert estudiante.nombres == "Ana María"
    assert response["Location"] == reverse("asistencia:estudiante_enrolar", args=[estudiante.pk])


@pytest.mark.parametrize(
    ("cedula", "mensaje"),
    [
        ("x; DROP", "10 dígitos"),
        ("091234567", "10 dígitos"),
        ("0912345678", "dígito verificador"),
        ("2510034065", "provincia"),
        ("1770034065", "tercer dígito"),
    ],
)
def test_create_student_rejects_invalid_ecuadorian_id(cliente, cedula, mensaje):
    response = cliente.post(
        reverse("asistencia:estudiante_nuevo"),
        {"cedula": cedula, "nombres": "A", "apellidos": "B"},
    )
    assert response.status_code == 200
    assert mensaje in " ".join(response.context["form"].errors["cedula"])
    assert not Estudiante.objects.exists()


def test_create_student_rejects_duplicate_id(cliente, estudiante):
    response = cliente.post(
        reverse("asistencia:estudiante_nuevo"),
        {"cedula": estudiante.cedula, "nombres": "Otro", "apellidos": "Igual"},
    )
    assert "Ya existe" in " ".join(response.context["form"].errors["cedula"])
    assert Estudiante.objects.count() == 1


def test_student_search_filters_list(cliente, estudiante):
    Estudiante.objects.create(cedula="1710034065", nombres="Luis", apellidos="Mora")
    response = cliente.get(reverse("asistencia:estudiantes"), {"q": "Pérez"})
    assert list(response.context["estudiantes"]) == [estudiante]


def test_update_and_delete_student(cliente, estudiante):
    url = reverse("asistencia:estudiante_editar", args=[estudiante.pk])
    cliente.post(url, {"cedula": estudiante.cedula, "nombres": "Ana", "apellidos": "Ruiz"})
    estudiante.refresh_from_db()
    assert estudiante.apellidos == "Ruiz" and estudiante.activo is False
    cliente.post(reverse("asistencia:estudiante_eliminar", args=[estudiante.pk]))
    assert not Estudiante.objects.exists()


def test_delete_requires_post(cliente, estudiante):
    response = cliente.get(reverse("asistencia:estudiante_eliminar", args=[estudiante.pk]))
    assert response.status_code == 405


# --- Enrolamiento (API) ---------------------------------------------------


def test_register_sample_stores_embedding_and_image(cliente, estudiante, fake_engine, jpeg_bytes):
    url = reverse("asistencia:api_muestra", args=[estudiante.pk])
    response = cliente.post(url, {"frame": frame(jpeg_bytes)})
    assert response.status_code == 201
    muestra = MuestraRostro.objects.get()
    assert muestra.vector().shape == (128,)
    assert response.json()["data"]["total"] == 1
    assert (
        cliente.get(reverse("asistencia:estudiante_enrolar", args=[estudiante.pk])).status_code
        == 200
    )


def test_register_sample_rejects_photo_without_face(cliente, estudiante, fake_engine, jpeg_bytes):
    fake_engine.enrollment_error = "No se detectó ningún rostro."
    response = cliente.post(
        reverse("asistencia:api_muestra", args=[estudiante.pk]), {"frame": frame(jpeg_bytes)}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "No se detectó ningún rostro."


def test_register_sample_enforces_limit(cliente, estudiante, fake_engine, jpeg_bytes, settings):
    settings.VISION = {**settings.VISION, "MAX_SAMPLES_PER_STUDENT": 1}
    url = reverse("asistencia:api_muestra", args=[estudiante.pk])
    cliente.post(url, {"frame": frame(jpeg_bytes)})
    response = cliente.post(url, {"frame": frame(jpeg_bytes)})
    assert response.status_code == 422 and "máximo" in response.json()["error"]


def test_delete_sample(cliente, estudiante, fake_engine, jpeg_bytes):
    muestra = services.registrar_muestra(estudiante, jpeg_bytes)
    cliente.post(reverse("asistencia:muestra_eliminar", args=[muestra.pk]))
    assert not MuestraRostro.objects.exists()


# --- Procesamiento en vivo (API) ------------------------------------------


def procesar(cliente, jpeg, sesion=None, **extra):
    data = {"frame": frame(jpeg), "sesion": sesion.pk if sesion else "", **extra}
    return cliente.post(reverse("asistencia:api_procesar"), data)


def test_process_frame_returns_annotated_image_and_faces(cliente, fake_engine, jpeg_bytes):
    response = procesar(cliente, jpeg_bytes, modo="bordes")
    body = response.json()
    assert response.status_code == 200 and body["ok"]
    assert body["data"]["imagen"].startswith("data:image/jpeg;base64,")
    assert body["data"]["total_rostros"] == 1
    assert body["data"]["desconocidos"] == 1


def test_process_frame_without_image_returns_only_face_data(cliente, fake_engine, jpeg_bytes):
    body = procesar(cliente, jpeg_bytes, imagen="0").json()["data"]
    assert body["imagen"] is None
    assert (body["ancho"], body["alto"]) == (320, 240)
    rostro = body["rostros"][0]
    assert rostro["box"] == [40, 40, 80, 100]
    assert len(rostro["puntos"]) == 5


def test_attendance_registered_after_three_consecutive_recognitions(
    cliente, docente, estudiante, fake_engine, jpeg_bytes
):
    services.registrar_muestra(estudiante, jpeg_bytes)
    fake_engine.label = estudiante.pk
    sesion = nueva_sesion(docente)
    respuestas = [procesar(cliente, jpeg_bytes, sesion).json()["data"] for _ in range(4)]
    nuevas = [len(r["nuevas_asistencias"]) for r in respuestas]
    assert nuevas == [0, 0, 1, 0]
    assert respuestas[1]["rostros"][0]["progreso"] == pytest.approx(0.67, abs=0.01)
    assert respuestas[3]["rostros"][0]["confirmado"] is True
    assert respuestas[2]["rostros"][0]["nombre"] == "Ana Pérez"
    asistencia = Asistencia.objects.get()
    assert asistencia.estudiante == estudiante and asistencia.evidencia


def test_no_attendance_without_session_or_in_closed_session(
    cliente, docente, estudiante, fake_engine, jpeg_bytes
):
    fake_engine.label = estudiante.pk
    cerrada = nueva_sesion(docente)
    cerrada.cerrar()
    for _ in range(4):
        procesar(cliente, jpeg_bytes)
        procesar(cliente, jpeg_bytes, cerrada)
    assert not Asistencia.objects.exists()


def test_process_frame_rejects_invalid_image(cliente, fake_engine):
    response = procesar(cliente, b"basura")
    assert response.status_code == 400


def test_process_frame_requires_frame_field(cliente, fake_engine):
    response = cliente.post(reverse("asistencia:api_procesar"), {})
    assert response.status_code == 400


def test_process_frame_rejects_non_numeric_session(cliente, fake_engine, jpeg_bytes):
    response = cliente.post(
        reverse("asistencia:api_procesar"), {"frame": frame(jpeg_bytes), "sesion": "1 OR 1=1"}
    )
    assert response.status_code == 400


def test_process_frame_returns_503_when_models_missing(cliente, jpeg_bytes, monkeypatch):
    def sin_modelos():
        raise ModelUnavailableError("Ejecute: python manage.py descargar_modelos")

    monkeypatch.setattr(services, "get_engine", sin_modelos)
    response = procesar(cliente, jpeg_bytes)
    assert response.status_code == 503 and "descargar_modelos" in response.json()["error"]


def test_process_frame_hides_internal_errors(cliente, jpeg_bytes, monkeypatch):
    def falla():
        raise RuntimeError("detalle interno secreto")

    monkeypatch.setattr(services, "get_engine", falla)
    response = procesar(cliente, jpeg_bytes)
    assert response.status_code == 500
    assert "secreto" not in response.json()["error"]


# --- Sesiones --------------------------------------------------------------


def test_create_session_redirects_to_monitor(cliente, docente):
    response = cliente.post(reverse("asistencia:sesiones"), {"asignatura": "Construcción"})
    sesion = SesionClase.objects.get()
    assert sesion.docente == docente and sesion.activa
    assert response["Location"].endswith(f"?sesion={sesion.pk}")


def test_only_one_active_session_allowed(cliente, docente):
    nueva_sesion(docente)
    cliente.post(reverse("asistencia:sesiones"), {"asignatura": "Otra"})
    assert SesionClase.objects.count() == 1


def test_close_session_and_detail_stats(cliente, docente, estudiante):
    sesion = nueva_sesion(docente)
    Asistencia.objects.create(sesion=sesion, estudiante=estudiante, similitud=0.8)
    Estudiante.objects.create(cedula="0102030400", nombres="Luis", apellidos="Mora")
    cliente.post(reverse("asistencia:sesion_cerrar", args=[sesion.pk]))
    sesion.refresh_from_db()
    assert not sesion.activa
    response = cliente.get(reverse("asistencia:sesion_detalle", args=[sesion.pk]))
    assert response.context["stats"] == {
        "inscritos": 2,
        "presentes": 1,
        "ausentes": 1,
        "porcentaje": 50.0,
    }


def test_csv_export_marks_present_and_absent_and_escapes_formulas(cliente, docente, estudiante):
    sesion = nueva_sesion(docente)
    Asistencia.objects.create(sesion=sesion, estudiante=estudiante, similitud=0.8)
    Estudiante.objects.create(cedula="1312345679", nombres="=HYPERLINK(1)", apellidos="Mora")
    response = cliente.get(reverse("asistencia:sesion_csv", args=[sesion.pk]))
    contenido = response.content.decode("utf-8-sig")
    assert "Presente" in contenido and "Ausente" in contenido
    assert "'=HYPERLINK(1)" in contenido


def test_gallery_cache_reloads_when_samples_change(estudiante, fake_engine, jpeg_bytes):
    cache = services.GalleryCache()
    gallery, _ = cache.get()
    assert gallery.is_empty
    services.registrar_muestra(estudiante, jpeg_bytes)
    gallery, names = cache.get()
    assert gallery.labels == (estudiante.pk,)
    assert names[estudiante.pk] == "Ana Pérez"


def test_pages_version_js_modules_and_css_to_avoid_stale_cache(cliente):
    html = cliente.get(reverse("asistencia:monitor")).content.decode()
    assert '<script type="importmap">' in html
    assert "/static/asistencia/js/monitor.js?v=" in html
    assert "/static/asistencia/js/overlay.js?v=" in html
    assert "/static/asistencia/css/app.css?v=" in html
