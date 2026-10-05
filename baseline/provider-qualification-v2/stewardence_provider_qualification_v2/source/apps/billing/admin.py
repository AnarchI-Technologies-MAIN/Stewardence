from django.contrib import admin

from .models import BillingCustomer, Subscription

admin.site.register(BillingCustomer)
admin.site.register(Subscription)
