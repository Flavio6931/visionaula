"""URLconf de las pruebas E2E: igual a la del proyecto, más el servicio de /media/.

Durante las pruebas DEBUG es False, así que config.urls no publica los archivos
subidos; aquí se agregan para que las miniaturas se vean en las capturas.
"""

from django.conf import settings
from django.urls import re_path
from django.views.static import serve

from config.urls import urlpatterns as urls_proyecto

urlpatterns = [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    *urls_proyecto,
]
