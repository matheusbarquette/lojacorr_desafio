from rest_framework.routers import DefaultRouter
from .views import SeguradoraViewSet

router = DefaultRouter()
router.register("seguradoras", SeguradoraViewSet, basename="seguradora")
urlpatterns = router.urls
