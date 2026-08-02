from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from seguradoras.views import health

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('seguradoras.urls')),

    # Documentação interativa: /api/docs/ é a interface, /api/schema/ é o OpenAPI cru.
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    path('health/', health, name='health'),
]
