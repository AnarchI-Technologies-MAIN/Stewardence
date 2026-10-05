from django.urls import path
from apps.billing.admission_views import paid_webhook
urlpatterns = [path("billing/paid-webhook/", paid_webhook, name="paid-webhook")]
