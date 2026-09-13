from rest_framework import serializers

from .models import (
    AccountingPeriod,
    Contract,
    Evidence,
    Invoice,
    Payment,
    PerformanceObligation,
    UsageRecord,
)


class PeriodSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)

    class Meta:
        model = AccountingPeriod
        fields = ["id", "year", "month", "label", "is_closed", "closed_at"]


class ContractListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contract
        fields = ["id", "number", "customer", "signed_date", "total_price", "note"]


class InvoiceSerializer(serializers.ModelSerializer):
    period_label = serializers.CharField(source="period.label", read_only=True)

    class Meta:
        model = Invoice
        fields = ["id", "contract", "number", "invoice_date", "amount", "period", "period_label"]


class PaymentSerializer(serializers.ModelSerializer):
    period_label = serializers.CharField(source="period.label", read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "contract", "received_date", "amount", "period", "period_label"]


class EvidenceSerializer(serializers.ModelSerializer):
    period_label = serializers.CharField(source="period.label", read_only=True)

    class Meta:
        model = Evidence
        fields = [
            "id", "obligation", "title", "reference", "accepted_date",
            "period", "period_label", "note",
        ]
        read_only_fields = ["period"]


class UsageRecordSerializer(serializers.ModelSerializer):
    period_label = serializers.CharField(source="period.label", read_only=True)

    class Meta:
        model = UsageRecord
        fields = ["id", "obligation", "period", "period_label", "quantity", "note"]


class ReallocateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)


class EvidenceCreateSerializer(serializers.Serializer):
    obligation = serializers.PrimaryKeyRelatedField(
        queryset=PerformanceObligation.objects.all()
    )
    title = serializers.CharField(max_length=128)
    reference = serializers.CharField(max_length=64)
    accepted_date = serializers.DateField()
    note = serializers.CharField(required=False, allow_blank=True, default="")
