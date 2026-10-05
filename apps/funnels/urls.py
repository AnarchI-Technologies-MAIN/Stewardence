from django.urls import path
from .views import experience, bundle_json
app_name = "funnels"
urlpatterns = [
    path("preview/<slug:scenario>/", experience, {"preview": True}, name="preview"),
    path("bundle/<slug:scenario>.json", bundle_json, name="bundle"),
    path("<slug:scenario>/", experience, name="experience"),
]
