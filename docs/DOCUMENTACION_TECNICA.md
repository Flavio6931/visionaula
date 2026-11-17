# Documentación técnica: VisionAula

Sistema web de control de asistencia con reconocimiento facial en tiempo real
(Django + OpenCV + PostgreSQL).

## 1. Requisitos

### 1.1 Hardware
- Computador con cámara web (integrada o USB), 4 GB de RAM o más.
- Procesador x64; no requiere GPU (las redes YuNet y SFace corren en CPU en unos 25 ms por fotograma).

### 1.2 Software
| Componente | Versión | Uso |
|---|---|---|
| Python | 3.10 o superior (probado con 3.12 y 3.14) | Backend |
| Django | ≥ 5.2, < 6.2 | Framework web |
| opencv-python | ≥ 4.10 | Detección, reconocimiento y procesamiento de imagen |
| NumPy | ≥ 1.26 | Operaciones con matrices y vectores |
| PostgreSQL | 14 o superior (probado con 17) | Base de datos |
| psycopg | ≥ 3.2 | Conector de PostgreSQL |
| Pillow, python-dotenv | ≥ 10.4 / ≥ 1.0 | Imágenes en Django / variables de entorno |
| Navegador | Chrome, Edge o Firefox actuales | Interfaz y acceso a la cámara (`getUserMedia`) |

**Solo para desarrollo y pruebas** (`requirements-dev.txt`): pytest, pytest-django, pytest-cov,
Playwright y ruff.

### 1.3 Requisitos funcionales implementados
| ID | Requisito |
|---|---|
| RF-01 | Autenticación del docente; todas las páginas y la API exigen sesión iniciada |
| RF-02 | CRUD de estudiantes con validación de la cédula ecuatoriana |
| RF-03 | Registro del rostro del estudiante (3 a 10 fotos) desde la cámara o subiendo una foto |
| RF-04 | Apertura y cierre de sesiones de clase (solo una activa a la vez) |
| RF-05 | Detección y reconocimiento de rostros en video en tiempo real |
| RF-06 | Registro automático de asistencia tras 3 reconocimientos consecutivos, sin duplicados |
| RF-07 | Pixelado automático de personas no registradas (privacidad) |
| RF-08 | Filtros de procesamiento: normal, CLAHE, grises, bordes (Canny) y mapa térmico |
| RF-09 | Estadísticas de la sesión y exportación a CSV |

## 2. Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/Flavio6931/visionaula.git
cd visionaula

# 2. Entorno virtual
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # Linux / macOS

# 3. Dependencias
pip install -r requirements.txt
```

4. **Base de datos.** Crear la base en PostgreSQL:
   ```sql
   CREATE DATABASE visionaula;
   ```
   Opcional: `docker compose up -d` levanta PostgreSQL 17 listo para usar.

5. **Configuración.** Copiar `.env.example` como `.env` y completar los valores:

   | Variable | Descripción | Ejemplo |
   |---|---|---|
   | `DJANGO_DEBUG` | Modo depuración (solo desarrollo) | `True` |
   | `DJANGO_SECRET_KEY` | Clave secreta de Django (obligatoria si `DEBUG=False`) | *generada* |
   | `DJANGO_ALLOWED_HOSTS` | Dominios permitidos | `localhost,127.0.0.1` |
   | `DB_ENGINE` | `postgresql` (requerido) o `sqlite` (pruebas rápidas) | `postgresql` |
   | `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Conexión a PostgreSQL | `visionaula`, `postgres`, …, `localhost`, `5432` |
   | `VISION_MATCH_THRESHOLD` | Similitud mínima para reconocer (0 a 1) | `0.40` |
   | `VISION_DETECTION_SCORE` | Confianza mínima de YuNet | `0.80` |
   | `VISION_MIN_FACE_SIZE` | Tamaño mínimo del rostro en píxeles | `40` |
   | `VISION_CONFIRM_FRAMES` / `VISION_CONFIRM_WINDOW_SECONDS` | Reconocimientos seguidos y ventana de tiempo para registrar asistencia | `3` / `4` |
   | `VISION_MAX_SAMPLES` | Fotos máximas por estudiante | `10` |

   Generar la clave secreta:
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
   ```

6. **Migraciones, modelos de OpenCV y usuario docente:**
   ```bash
   python manage.py migrate
   python manage.py descargar_modelos     # YuNet y SFace, verificados con SHA-256
   python manage.py createsuperuser
   ```

## 3. Ejecución

```bash
python manage.py runserver
```

Abrir <http://localhost:8000>. El navegador solo permite usar la cámara en `localhost` o con HTTPS.
El panel de administración de Django está en <http://localhost:8000/admin/>.

## 4. Estructura de directorios

```
visionaula/
├── config/                     Proyecto Django
│   ├── settings.py             Configuración (lee el archivo .env)
│   ├── urls.py                 Rutas raíz: admin, login y aplicación
│   └── wsgi.py / asgi.py
├── asistencia/                 Aplicación principal
│   ├── models.py               Estudiante, MuestraRostro, SesionClase, Asistencia
│   ├── views.py                Vistas HTML (panel, estudiantes, sesiones, monitor, CSV)
│   ├── api.py                  API JSON: procesar fotograma y registrar muestra
│   ├── services.py             Lógica de negocio: une OpenCV con la base de datos
│   ├── tracker.py              Confirmación temporal (3 reconocimientos seguidos)
│   ├── validators.py           Validación de la cédula ecuatoriana (módulo 10)
│   ├── forms.py / admin.py / signals.py / urls.py
│   ├── management/commands/descargar_modelos.py
│   ├── migrations/
│   ├── templates/asistencia/   Plantillas HTML
│   └── static/asistencia/      CSS y JavaScript (cámara, monitor, overlay, registro)
├── vision/                     Módulo de visión (independiente de Django)
│   ├── codec.py                Decodificar/codificar JPEG con límites de tamaño
│   ├── preprocessing.py        CLAHE, calidad del rostro y filtros
│   ├── detector.py             Detección con YuNet (cv2.FaceDetectorYN)
│   ├── recognizer.py           Reconocimiento con SFace (cv2.FaceRecognizerSF)
│   ├── annotator.py            Dibujo de marcos, puntos, etiquetas y pixelado
│   ├── pipeline.py             Orquestación de todas las etapas
│   └── model_store.py          Descarga y verificación de los modelos ONNX
├── templates/                  base.html y registration/login.html
├── modelos/                    Modelos ONNX (se descargan, no se suben)
├── tests/                      Pruebas automatizadas (pytest)
│   ├── fixtures/rostros/       Retratos de dominio público para las pruebas
│   ├── test_vision_unit.py     Unitarias del módulo de visión
│   ├── test_vision_models.py   Unitarias con las redes YuNet y SFace reales
│   ├── test_validators.py      Unitarias de la cédula
│   ├── test_model_store.py     Unitarias de descarga de modelos y del comando
│   ├── test_django.py          Integración: rutas, API, vistas y base de datos
│   ├── test_regresiones.py     Integración: regresiones de la revisión de código
│   ├── test_funcionales.py     Funcionales: casos de uso con OpenCV real
│   └── test_e2e_interfaz.py    E2E: navegador real con cámara simulada
├── docs/                       Documentación, casos de prueba y reportes
│   └── pruebas/                Log, JUnit XML y capturas de las pruebas
├── .github/workflows/pruebas.yml   CI: lint + pruebas sobre PostgreSQL
├── requirements.txt / requirements-dev.txt
├── pytest.ini / ruff.toml / docker-compose.yml
└── manage.py
```

## 5. Arquitectura

```
Navegador (JavaScript)                    Servidor Django                       OpenCV (vision/)
──────────────────────                    ───────────────                       ────────────────
getUserMedia → <video>                                                          
  cada ~40 ms: captura JPEG ──POST /api/procesar/──► api.procesar_frame          
                                           services.procesar_frame ─────────►  pipeline.analyze
                                                                                 ├ resize + CLAHE si hay poca luz
                                                                                 ├ YuNet: rostros + 5 puntos
                                                                                 └ SFace: vector 128-D → similitud
                                           tracker: 3 aciertos seguidos ◄──────  resultados
                                           Asistencia.save() → PostgreSQL
  overlay.js dibuja marcos, nombres  ◄──── JSON {rostros, nuevas_asistencias, …}
  y pixela a los desconocidos
```

**Decisiones de diseño**
- **Reconocimiento por similitud coseno:** cada rostro se convierte en un vector de 128 valores;
  si la similitud con alguna muestra registrada es ≥ 0.40 se identifica al estudiante.
- **Confirmación temporal:** se exigen 3 reconocimientos dentro de 4 s para evitar falsos positivos.
- **Integridad en la base de datos:** restricción única `(sesión, estudiante)` y un índice parcial
  que solo permite una sesión abierta, incluso con peticiones simultáneas.
- **Rendimiento:** detección sobre una copia reducida (960 px), galería en memoria que solo se
  recarga cuando cambian los datos, y dibujo del resultado en el navegador.
- **Seguridad y privacidad:** login obligatorio, CSRF, límite de 4 MB por imagen, mensajes de error
  sin detalles internos, CSV protegido contra inyección de fórmulas y pixelado automático de
  personas no registradas. Al eliminar un estudiante se borran sus fotos y evidencias.

## 6. Modelo de datos

| Tabla | Campos principales | Reglas |
|---|---|---|
| `Estudiante` | cédula, nombres, apellidos, correo, curso, activo | Cédula única y válida |
| `MuestraRostro` | estudiante, embedding (128 float32), imagen, calidad | Máximo 10 por estudiante |
| `SesionClase` | asignatura, tema, docente, inicio, fin | Solo una sesión con `fin` vacío |
| `Asistencia` | sesión, estudiante, hora, similitud, evidencia (foto) | Única por sesión y estudiante |

## 7. API JSON

Respuesta uniforme: `{"ok": bool, "data": {...} | null, "error": str | null}`.

| Método y ruta | Parámetros (multipart) | Respuestas |
|---|---|---|
| `POST /api/procesar/` | `frame` (JPEG), `sesion` (id opcional), `modo` (filtro), `imagen` (`1`/`0`) | 200 rostros y asistencias nuevas · 400 imagen inválida · 401 sin sesión · 503 faltan modelos |
| `POST /api/estudiantes/<id>/muestras/` | `frame` (JPEG con un solo rostro) | 201 muestra guardada · 422 sin rostro, varios rostros, borrosa o límite alcanzado |

## 8. Pruebas realizadas

Se ejecutaron **132 pruebas automatizadas: todas aprobadas, con un 99 % de cobertura de código**.
Detalle completo en
[`docs/pruebas/REPORTE_PRUEBAS.md`](pruebas/REPORTE_PRUEBAS.md).

| Tipo | Cantidad | Herramienta |
|---|---|---|
| Unitarias (incluye redes reales) | 67 | pytest |
| Integración (rutas, API, BD) | 48 | pytest-django |
| Funcionales (casos de uso) | 15 | pytest + OpenCV real |
| E2E (navegador) | 2 | Playwright + Chrome con cámara simulada |

```bash
pip install -r requirements-dev.txt
pytest --cov=vision --cov=asistencia --cov-report=term-missing
```

La integración continua (`.github/workflows/pruebas.yml`) ejecuta en cada *push* el linter
(ruff), las migraciones y toda la suite contra **PostgreSQL 17**, y exige un 80 % de cobertura mínima.
