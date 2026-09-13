import functools

from django.db.models import Sum
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import (
    AccountingPeriod,
    Contract,
    Evidence,
    Invoice,
    Payment,
    RecognitionEntry,
    UsageRecord,
)
from .serializers import (
    ContractListSerializer,
    EvidenceCreateSerializer,
    EvidenceSerializer,
    InvoiceSerializer,
    PaymentSerializer,
    PeriodSerializer,
    ReallocateSerializer,
    UsageRecordSerializer,
)


def domain_errors(view_func):
    """把业务规则错误转成 400。"""

    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        try:
            return view_func(*args, **kwargs)
        except services.DomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return wrapper


# ---------------------------------------------------------------- 装配明细

def _obligation_payload(ob):
    evidence = getattr(ob, "evidence", None)
    return {
        "id": ob.id,
        "name": ob.name,
        "kind": ob.kind,
        "kind_label": ob.get_kind_display(),
        "ssp": ob.ssp,
        "service_start": ob.service_start,
        "service_end": ob.service_end,
        "estimated_units": ob.estimated_units,
        "unit_label": ob.unit_label,
        "evidence": (
            {
                "id": evidence.id,
                "title": evidence.title,
                "reference": evidence.reference,
                "accepted_date": evidence.accepted_date,
                "period": evidence.period.label,
            }
            if evidence
            else None
        ),
        "usage_records": [
            {
                "id": r.id,
                "period": r.period.label,
                "quantity": r.quantity,
                "note": r.note,
            }
            for r in ob.usage_records.all()
        ],
    }


def _version_payload(version):
    return {
        "id": version.id,
        "version_no": version.version_no,
        "reason": version.reason,
        "created_at": version.created_at,
        "total_price": version.total_price,
        "total_ssp": version.total_ssp,
        "residual_amount": version.residual_amount,
        "residual_obligation_id": version.residual_obligation_id,
        "lines": [
            {
                "id": line.id,
                "obligation_id": line.obligation_id,
                "obligation_name": line.obligation.name,
                "ssp": line.ssp,
                "ratio": line.ratio,
                "allocated_amount": line.allocated_amount,
                "is_residual_receiver": line.is_residual_receiver,
            }
            for line in version.lines.all()
        ],
    }


def contract_detail_payload(contract: Contract) -> dict:
    versions = list(
        contract.allocation_versions.prefetch_related("lines__obligation").order_by(
            "-version_no"
        )
    )
    entries = (
        RecognitionEntry.objects.filter(obligation__contract=contract)
        .select_related("period", "allocation_line__version", "obligation")
        .order_by("period__year", "period__month", "id")
    )
    return {
        "id": contract.id,
        "number": contract.number,
        "customer": contract.customer,
        "signed_date": contract.signed_date,
        "total_price": contract.total_price,
        "note": contract.note,
        "obligations": [
            _obligation_payload(ob) for ob in contract.obligations.prefetch_related(
                "usage_records__period", "evidence__period"
            )
        ],
        "current_allocation": _version_payload(versions[0]) if versions else None,
        "allocation_versions": [_version_payload(v) for v in versions],
        "entries": [
            {
                "id": e.id,
                "obligation_id": e.obligation_id,
                "obligation_name": e.obligation.name,
                "period": e.period.label if e.period_id else None,
                "amount": e.amount,
                "status": e.status,
                "status_label": e.get_status_display(),
                "source": e.source,
                "source_label": e.get_source_display(),
                "note": e.note,
                # 追溯链：确认行 → 分配行 → 分配版本
                "allocation_line_id": e.allocation_line_id,
                "allocation_version_no": e.allocation_line.version.version_no,
            }
            for e in entries
        ],
        "invoices": InvoiceSerializer(contract.invoices.all(), many=True).data,
        "payments": PaymentSerializer(contract.payments.all(), many=True).data,
        "reconciliation": services.contract_reconciliation(contract),
        "totals": services.contract_totals(contract),
    }


# ---------------------------------------------------------------- 视图

class PeriodViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = AccountingPeriod.objects.all()
    serializer_class = PeriodSerializer

    @action(detail=True, methods=["post"])
    @domain_errors
    def close(self, request, pk=None):
        period = self.get_object()
        services.close_period(period)
        return Response(PeriodSerializer(period).data)


class ContractViewSet(viewsets.GenericViewSet):
    queryset = Contract.objects.all()

    def list(self, request):
        rows = []
        for contract in self.get_queryset():
            data = ContractListSerializer(contract).data
            data["totals"] = services.contract_totals(contract)
            rows.append(data)
        return Response(rows)

    def retrieve(self, request, pk=None):
        return Response(contract_detail_payload(self.get_object()))

    @action(detail=True, methods=["post"])
    @domain_errors
    def reallocate(self, request, pk=None):
        serializer = ReallocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        version = services.reallocate(self.get_object(), serializer.validated_data["reason"])
        return Response(_version_payload(version), status=status.HTTP_201_CREATED)


class InvoiceViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer

    @domain_errors
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.assert_period_open(serializer.validated_data["period"])
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @domain_errors
    def destroy(self, request, *args, **kwargs):
        invoice = self.get_object()
        services.assert_period_open(invoice.period)
        return super().destroy(request, *args, **kwargs)


class PaymentViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer

    @domain_errors
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.assert_period_open(serializer.validated_data["period"])
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @domain_errors
    def destroy(self, request, *args, **kwargs):
        payment = self.get_object()
        services.assert_period_open(payment.period)
        return super().destroy(request, *args, **kwargs)


class EvidenceViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = Evidence.objects.all()
    serializer_class = EvidenceSerializer

    @domain_errors
    def create(self, request, *args, **kwargs):
        serializer = EvidenceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        evidence = services.add_evidence(
            obligation=data["obligation"],
            title=data["title"],
            reference=data["reference"],
            accepted_date=data["accepted_date"],
            note=data["note"],
        )
        return Response(EvidenceSerializer(evidence).data, status=status.HTTP_201_CREATED)

    @domain_errors
    def destroy(self, request, *args, **kwargs):
        services.remove_evidence(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


class UsageRecordViewSet(
    mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    queryset = UsageRecord.objects.all()
    serializer_class = UsageRecordSerializer

    @domain_errors
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        record = services.add_usage_record(
            obligation=data["obligation"],
            period=data["period"],
            quantity=data["quantity"],
            note=data.get("note", ""),
        )
        return Response(self.get_serializer(record).data, status=status.HTTP_201_CREATED)

    @domain_errors
    def destroy(self, request, *args, **kwargs):
        services.remove_usage_record(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


class SummaryView(APIView):
    """财务三问：签了多少、收了多少、当期真正确认了多少，外加递延与待确认。"""

    def get(self, request):
        contracts = Contract.objects.all()
        totals = {
            "total_price": sum(c.total_price for c in contracts),
            "billed": Invoice.objects.aggregate(s=Sum("amount"))["s"] or 0,
            "received": Payment.objects.aggregate(s=Sum("amount"))["s"] or 0,
        }
        by_status = {
            row["status"]: row["s"]
            for row in RecognitionEntry.objects.values("status").annotate(s=Sum("amount"))
        }
        totals["recognized"] = by_status.get(RecognitionEntry.Status.RECOGNIZED, 0)
        totals["planned"] = by_status.get(RecognitionEntry.Status.PLANNED, 0)
        totals["pending"] = by_status.get(RecognitionEntry.Status.PENDING, 0)
        totals["deferred"] = totals["billed"] - totals["recognized"]
        totals["unbilled"] = totals["total_price"] - totals["billed"]
        totals["current_period"] = services.current_period().label
        return Response(totals)
