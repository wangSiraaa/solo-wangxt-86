from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ContractViewSet,
    EvidenceViewSet,
    InvoiceViewSet,
    PaymentViewSet,
    PeriodViewSet,
    SummaryView,
    UsageRecordViewSet,
)

router = DefaultRouter()
router.register("periods", PeriodViewSet, basename="period")
router.register("contracts", ContractViewSet, basename="contract")
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentViewSet, basename="payment")
router.register("evidence", EvidenceViewSet, basename="evidence")
router.register("usage-records", UsageRecordViewSet, basename="usage-record")

urlpatterns = [
    path("", include(router.urls)),
    path("summary/", SummaryView.as_view(), name="summary"),
]
