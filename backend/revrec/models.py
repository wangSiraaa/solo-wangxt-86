import calendar
from datetime import date

from django.db import models


class AccountingPeriod(models.Model):
    """会计期间。关闭后其中的记录不能直接编辑。"""

    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["year", "month"]
        constraints = [
            models.UniqueConstraint(fields=["year", "month"], name="uniq_period_year_month")
        ]

    def __str__(self):
        return self.label

    @property
    def label(self):
        return f"{self.year}-{self.month:02d}"

    @property
    def start_date(self):
        return date(self.year, self.month, 1)

    @property
    def end_date(self):
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])


class Contract(models.Model):
    """合同：签了多少（total_price）。"""

    number = models.CharField(max_length=32, unique=True)
    customer = models.CharField(max_length=128)
    signed_date = models.DateField()
    total_price = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.number} {self.customer}"


class PerformanceObligation(models.Model):
    """履约义务：合同的可区分组成，携带独立售价(SSP)。"""

    class Kind(models.TextChoices):
        SUBSCRIPTION = "SUBSCRIPTION", "账号订阅"
        IMPLEMENTATION = "IMPLEMENTATION", "一次性实施"
        USAGE = "USAGE", "按量服务"

    contract = models.ForeignKey(Contract, related_name="obligations", on_delete=models.CASCADE)
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    ssp = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="独立售价")
    # 订阅型
    service_start = models.DateField(null=True, blank=True)
    service_end = models.DateField(null=True, blank=True)
    # 按量型
    estimated_units = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="预计总量"
    )
    unit_label = models.CharField(max_length=16, blank=True, default="次")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.contract.number}/{self.name}"


class AllocationVersion(models.Model):
    """交易价格分摊的版本快照。任何确认金额都能追到某个版本。"""

    contract = models.ForeignKey(
        Contract, related_name="allocation_versions", on_delete=models.CASCADE
    )
    version_no = models.PositiveIntegerField()
    reason = models.CharField(max_length=200)
    total_price = models.DecimalField(max_digits=14, decimal_places=2)
    total_ssp = models.DecimalField(max_digits=14, decimal_places=2)
    residual_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    residual_obligation = models.ForeignKey(
        PerformanceObligation, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["contract", "version_no"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "version_no"], name="uniq_alloc_version")
        ]

    def __str__(self):
        return f"{self.contract.number} v{self.version_no}"


class AllocationLine(models.Model):
    """某版本中单个履约义务分到的金额。"""

    version = models.ForeignKey(AllocationVersion, related_name="lines", on_delete=models.CASCADE)
    obligation = models.ForeignKey(PerformanceObligation, on_delete=models.CASCADE)
    ssp = models.DecimalField(max_digits=14, decimal_places=2)  # 快照，防事后改价
    ratio = models.DecimalField(max_digits=20, decimal_places=10)
    allocated_amount = models.DecimalField(max_digits=14, decimal_places=2)
    is_residual_receiver = models.BooleanField(default=False)  # 尾差稳定归属标记

    class Meta:
        ordering = ["id"]


class Invoice(models.Model):
    """开票：只影响应收/递延，不直接是收入。"""

    contract = models.ForeignKey(Contract, related_name="invoices", on_delete=models.CASCADE)
    number = models.CharField(max_length=32, unique=True)
    invoice_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT)

    class Meta:
        ordering = ["period__year", "period__month", "id"]


class Payment(models.Model):
    """收款：现金口径，同样不等于收入。"""

    contract = models.ForeignKey(Contract, related_name="payments", on_delete=models.CASCADE)
    received_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT)

    class Meta:
        ordering = ["period__year", "period__month", "id"]


class Evidence(models.Model):
    """实施验收证据：实施类义务确认收入的前提。"""

    obligation = models.OneToOneField(
        PerformanceObligation, related_name="evidence", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=128)
    reference = models.CharField(max_length=64, verbose_name="验收单号")
    accepted_date = models.DateField()
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)


class UsageRecord(models.Model):
    """按量服务的实际用量记录。"""

    obligation = models.ForeignKey(
        PerformanceObligation, related_name="usage_records", on_delete=models.CASCADE
    )
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["period__year", "period__month", "id"]


class RecognitionEntry(models.Model):
    """收入确认计划行：归属某期间、某分配版本行。开票不产生这里的记录。"""

    class Status(models.TextChoices):
        PLANNED = "PLANNED", "计划(未来期间)"
        RECOGNIZED = "RECOGNIZED", "已确认"
        PENDING = "PENDING", "待确认(缺证据)"

    class Source(models.TextChoices):
        SUBSCRIPTION_SCHEDULE = "SUBSCRIPTION_SCHEDULE", "订阅直线分摊"
        IMPLEMENTATION_ACCEPTANCE = "IMPLEMENTATION_ACCEPTANCE", "实施验收"
        USAGE = "USAGE", "按量确认"

    obligation = models.ForeignKey(
        PerformanceObligation, related_name="recognition_entries", on_delete=models.CASCADE
    )
    allocation_line = models.ForeignKey(
        AllocationLine, related_name="entries", on_delete=models.CASCADE
    )
    period = models.ForeignKey(AccountingPeriod, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices)
    source = models.CharField(max_length=32, choices=Source.choices)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["period__year", "period__month", "id"]
