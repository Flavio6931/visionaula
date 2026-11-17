# Reporte de pruebas: VisionAula

**Fecha de ejecución:** 17/11/2026 · **Resultado:** ✅ **132 de 132 pruebas aprobadas** · **Cobertura:** **99 %**

| Evidencia | Archivo |
|---|---|
| Log completo de la ejecución (`pytest -v`) | [`reporte_pruebas.log`](reporte_pruebas.log) |
| Resultados en formato JUnit XML | [`resultados_junit.xml`](resultados_junit.xml) |
| Capturas de las pruebas E2E | [`capturas/`](capturas/) |
| Código de las pruebas | [`tests/`](../../tests/) |

## 1. Entorno de prueba

| Elemento | Versión |
|---|---|
| Sistema operativo | Windows 11 Pro |
| Python | 3.14 (compatible con 3.10 o superior) |
| Django / OpenCV / NumPy | 6.1 / 5.0 / 2.5 |
| Framework de pruebas | pytest 9 + pytest-django + pytest-cov |
| Navegador E2E | Playwright 1.65 + Google Chrome 157 (cámara simulada) |
| Base de datos | SQLite en local · **PostgreSQL 17 en GitHub Actions** (`.github/workflows/pruebas.yml`) |
| Modelos de OpenCV | YuNet 2023mar (detección) y SFace 2021dec (reconocimiento), verificados con SHA-256 |

## 2. Cómo ejecutar las pruebas

```bash
pip install -r requirements-dev.txt
python manage.py descargar_modelos
pytest                                   # toda la suite
pytest -m unit                           # solo unitarias
pytest -m integration                    # solo integración
pytest -m functional                     # solo funcionales (modelos reales)
pytest -m e2e                            # solo E2E en el navegador
pytest --cov=vision --cov=asistencia --cov-report=term-missing   # con cobertura
```

Las pruebas E2E usan Google Chrome instalado. Para usar el Chromium de Playwright:
`python -m playwright install chromium` y la variable `E2E_CHANNEL=chromium`.

## 3. Resumen por tipo de prueba

| Tipo (sesión de la guía) | Marca pytest | Archivos | Pruebas | Resultado |
|---|---|---|---|---|
| Unitarias (Sesión 1) | `unit` | `test_vision_unit.py`, `test_validators.py`, `test_model_store.py` | 58 | ✅ 58/58 |
| Unitarias con redes reales | `models` | `test_vision_models.py` | 9 | ✅ 9/9 |
| Integración (Sesión 1) | `integration` | `test_django.py`, `test_regresiones.py` | 48 | ✅ 48/48 |
| Funcionales (Sesión 2) | `functional` | `test_funcionales.py` | 15 | ✅ 15/15 |
| Extremo a extremo (Sesión 2) | `e2e` | `test_e2e_interfaz.py` | 2 | ✅ 2/2 |
| **Total** | | | **132** | ✅ **132/132** (23 s) |

## 4. Pruebas unitarias: funciones críticas

| Módulo | Qué se valida |
|---|---|
| `vision/codec.py` | Decodificación JPEG; rechazo de imágenes vacías, corruptas o mayores de 4 MB |
| `vision/preprocessing.py` | Detección de poca luz y mejora CLAHE; calidad del rostro (borroso, oscuro, sobreexpuesto); los 5 filtros |
| `vision/detector.py` | **YuNet real:** 1 rostro con 5 puntos faciales; orden por tamaño; descarte de rostros pequeños; recorte dentro de la imagen |
| `vision/recognizer.py` | **SFace real:** vector de 128 dimensiones normalizado; la misma persona supera el umbral (0.40) y otra persona no; galería vacía |
| `vision/pipeline.py` | Dibujo de marcos y nombres; **pixelado de rostros desconocidos** |
| `vision/model_store.py` | Descarga con verificación SHA-256; archivo alterado o sin red (con red simulada) |
| `asistencia/tracker.py` | Confirmación tras 3 reconocimientos seguidos; reinicio de la racha; sesiones independientes |
| `asistencia/validators.py` | Cédula ecuatoriana: longitud, provincia, tercer dígito y dígito verificador (módulo 10) |

## 5. Pruebas de integración: rutas principales de Django

| Ruta | Qué se valida |
|---|---|
| `/`, `/monitor/`, `/estudiantes/`, `/sesiones/` | Redirigen al login sin sesión (302) y responden 200 con sesión |
| `/estudiantes/nuevo/` | Normaliza datos; rechaza cédula inválida o duplicada |
| `/estudiantes/<id>/editar/` y `/eliminar/` | Edición; borrado solo por POST (405 con GET); borra fotos y evidencias |
| `/api/estudiantes/<id>/muestras/` | 201 al guardar; 422 sin rostro o al superar el máximo; 401 sin sesión |
| `/api/procesar/` | 200 con rostros; 400 imagen inválida o sesión no numérica; 503 sin modelos; 500 sin filtrar detalles internos |
| `/sesiones/`, `/sesiones/<id>/cerrar/` | Una sola sesión activa (restricción en la BD); cierre |
| `/sesiones/<id>/` y `/csv/` | Estadísticas correctas; CSV con Presente/Ausente y protección contra inyección de fórmulas |

## 6. Pruebas funcionales: casos de uso clave

Pipeline completo de OpenCV **sin simulaciones**, con dos retratos de la NASA (dominio público):
Neil Armstrong (estudiante registrado) y Buzz Aldrin (persona no registrada).

| ID | Caso de uso | Resultado esperado | Resultado |
|---|---|---|---|
| CU-01 | Inicio: el docente inicia sesión | Entra al panel; con clave incorrecta muestra error y no entra | ✅ |
| CU-02 | Registro de estudiante y de su rostro | Guarda al estudiante y la muestra (calidad > 0.5); rechaza foto sin rostro o con 2 personas (422) | ✅ |
| CU-03 | Detección en video (5 fotogramas en movimiento) | Detecta 1 rostro con 5 puntos y lo reconoce en cada fotograma; sin sesión no registra asistencia | ✅ |
| CU-04 | Toma de asistencia (Armstrong y Aldrin juntos) | Registra solo a Armstrong al 3.er fotograma y no lo duplica; Aldrin queda como desconocido | ✅ |
| CU-05 | Visualización en la interfaz | Los 5 filtros devuelven el video procesado; Aldrin pixelado y Armstrong visible; con poca luz aplica CLAHE y sigue reconociendo | ✅ |
| CU-06 | Cierre de la sesión y reporte | Inscritos 2, presentes 1, ausentes 1, 50 %; CSV correcto; con la sesión cerrada no registra más | ✅ |

**Valores medidos:** similitud de Armstrong ≈ 0.92 a 0.95 · de Aldrin ≈ 0.16 a 0.17 (umbral 0.40) ·
tiempo de procesamiento ≈ 22 a 25 ms por fotograma.

## 7. Pruebas de extremo a extremo (E2E) en el navegador

Playwright controla Google Chrome con una **cámara simulada** (video con los dos retratos) contra
el servidor de Django en ejecución. Recorre el flujo del docente y guarda una captura por paso:

| Paso | Verificación automática | Captura |
|---|---|---|
| Ruta protegida y login fallido | `/monitor/` redirige al login; muestra "Usuario o contraseña incorrectos" | `01-login-error.png` |
| Inicio de sesión | Se muestra el "Panel de control" | `02-login.png`, `03-panel.png` |
| Cédula inválida | "La cédula no es válida: el dígito verificador no coincide." | `04-cedula-invalida.png` |
| Captura con 2 personas | "Hay más de un rostro: solo el estudiante debe aparecer." | `05-registro-dos-rostros.png` |
| Registro de rostro | 3 fotos subidas, contador 3/10 | `06-registro-rostro.png` |
| Monitor en vivo | Rostros 2, desconocidos 1, "Neil Armstrong" registrado, resumen 1/2, overlay dibujado | `08-monitor-reconocimiento.png` |
| Filtros OpenCV | Bordes (Canny) y mapa térmico desde el servidor | `09-…bordes.png`, `10-…termico.png` |
| Reporte | 50,0 % de asistencia; cierre de la sesión; CSV descargado con Presente/Ausente | `11-detalle-sesion.png` |

## 8. Cobertura de código

| Paquete | Sentencias | Sin cubrir | Cobertura |
|---|---|---|---|
| `vision/` (módulo OpenCV) | 382 | 6 | 98 % |
| `asistencia/` (aplicación Django) | 610 | 8 | 99 % |
| **Total** | **992** | **14** | **99 %** (mínimo exigido en CI: 80 %) |

Las líneas sin cubrir son ramas defensivas (p. ej. fallo de `cv2.imencode`, región vacía al pixelar).

## 9. Pruebas manuales con cámara real

Los 27 casos de [`docs/CASOS_DE_PRUEBA.md`](../CASOS_DE_PRUEBA.md) se ejecutan con la cámara del
computador de cada integrante (permiso denegado, movimiento, poca luz real, varios estudiantes,
servidor detenido, etc.). Las pruebas automáticas anteriores cubren los mismos flujos de forma repetible.
