"""演示数据：三个完整案例。

案例A 跨年度服务：订阅 2025-07 ~ 2026-06 跨年，实施已验收，全额开票收款；
案例B 部分验收：两阶段实施只验收了阶段一，阶段二缺证据保持待确认，
        分摊产生 -0.01 尾差，稳定归属 SSP 最高的订阅义务；
案例C 预收未开通 + 按量：订阅服务期在未来（未开通，全部计划态），
        按量服务已发生两期用量，合同款已全额预收。

期间 2025-01 ~ 2026-08 关闭，当前期间 2026-09 保持打开。
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import connection

from revrec import services
from revrec.models import (
    AccountingPeriod,
    Contract,
    Evidence,
    Invoice,
    Payment,
    PerformanceObligation,
    RecognitionEntry,
    UsageRecord,
)


class Command(BaseCommand):
    help = "重建演示数据（会清空现有业务数据）"

    def handle(self, *args, **options):
        self._wipe()
        self._periods()
        self._case_a()
        self._case_b()
        self._case_c()
        self._close_periods()
        self.stdout.write(self.style.SUCCESS("演示数据已就绪"))
        self._print_summary()

    # ------------------------------------------------------------

    def _wipe(self):
        Contract.objects.all().delete()  # 级联义务/版本/分配行/确认/发票/收款/证据/用量
        AccountingPeriod.objects.all().delete()
        # 重置自增序列，保证重复种子后 ID 稳定
        with connection.cursor() as cursor:
            for table in (
                "revrec_contract", "revrec_performanceobligation",
                "revrec_allocationversion", "revrec_allocationline",
                "revrec_invoice", "revrec_payment", "revrec_evidence",
                "revrec_usagerecord", "revrec_recognitionentry",
                "revrec_accountingperiod",
            ):
                cursor.execute(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1")

    def _periods(self):
        for year, months in ((2025, range(1, 13)), (2026, range(1, 13)), (2027, range(1, 13))):
            for month in months:
                services.ensure_period(year, month)

    def _close_periods(self):
        for period in AccountingPeriod.objects.order_by("year", "month"):
            if (period.year, period.month) <= (2026, 8):
                services.close_period(period)

    @staticmethod
    def _invoice(contract, number, d, amount):
        Invoice.objects.create(
            contract=contract, number=number, invoice_date=d,
            amount=amount, period=services.period_for(d),
        )

    @staticmethod
    def _payment(contract, d, amount):
        Payment.objects.create(
            contract=contract, received_date=d,
            amount=amount, period=services.period_for(d),
        )

    # ------------------------------------------------------------ 案例A

    def _case_a(self):
        contract = Contract.objects.create(
            number="HT-2025-001", customer="云谷科技",
            signed_date=date(2025, 6, 15), total_price="131000.00",
            note="案例A：跨年度订阅 + 一次性实施（已验收）",
        )
        sub = PerformanceObligation.objects.create(
            contract=contract, name="账号订阅(50席)", kind="SUBSCRIPTION",
            ssp="120000.00",
            service_start=date(2025, 7, 1), service_end=date(2026, 6, 30),
        )
        impl = PerformanceObligation.objects.create(
            contract=contract, name="一次性实施部署", kind="IMPLEMENTATION",
            ssp="20000.00",
        )
        Evidence.objects.create(
            obligation=impl, title="实施验收报告", reference="YS-2025-0816",
            accepted_date=date(2025, 8, 20), period=services.period_for(date(2025, 8, 20)),
        )
        services.reallocate(contract, "合同签订，初始分摊")
        self._invoice(contract, "FP-2025-0701", date(2025, 7, 5), "131000.00")
        self._payment(contract, date(2025, 7, 20), "131000.00")
        assert sub and impl  # 明示义务已建

    # ------------------------------------------------------------ 案例B

    def _case_b(self):
        contract = Contract.objects.create(
            number="HT-2025-002", customer="岚桥制造",
            signed_date=date(2025, 12, 10), total_price="100000.00",
            note="案例B：两阶段实施部分验收（阶段二待确认），订阅当年有效",
        )
        PerformanceObligation.objects.create(
            contract=contract, name="实施-阶段一(核心上线)", kind="IMPLEMENTATION",
            ssp="30000.00",
        )
        PerformanceObligation.objects.create(
            contract=contract, name="实施-阶段二(扩展模块)", kind="IMPLEMENTATION",
            ssp="30000.00",
        )
        PerformanceObligation.objects.create(
            contract=contract, name="账号订阅(30席)", kind="SUBSCRIPTION",
            ssp="50000.00",
            service_start=date(2026, 1, 1), service_end=date(2026, 12, 31),
        )
        services.reallocate(contract, "合同签订，初始分摊")
        # 阶段一已验收（2026-01），阶段二无证据 → 待确认
        phase1 = contract.obligations.get(name__startswith="实施-阶段一")
        services.add_evidence(
            phase1, "阶段一验收单", "YS-2026-0103", date(2026, 1, 15),
        )
        self._invoice(contract, "FP-2025-1201", date(2025, 12, 20), "50000.00")
        self._payment(contract, date(2025, 12, 28), "50000.00")
        self._invoice(contract, "FP-2026-0601", date(2026, 6, 10), "50000.00")
        self._payment(contract, date(2026, 6, 30), "30000.00")  # 部分收款

    # ------------------------------------------------------------ 案例C

    def _case_c(self):
        contract = Contract.objects.create(
            number="HT-2026-003", customer="北辰零售",
            signed_date=date(2026, 5, 20), total_price="54000.00",
            note="案例C：全额预收，订阅未开通（服务期在未来），按量服务已发生",
        )
        PerformanceObligation.objects.create(
            contract=contract, name="账号订阅(20席,未开通)", kind="SUBSCRIPTION",
            ssp="48000.00",
            service_start=date(2026, 10, 1), service_end=date(2027, 9, 30),
        )
        usage = PerformanceObligation.objects.create(
            contract=contract, name="按量API调用", kind="USAGE",
            ssp="12000.00", estimated_units="12000.00", unit_label="次",
        )
        services.reallocate(contract, "合同签订，初始分摊")
        self._invoice(contract, "FP-2026-0602", date(2026, 6, 5), "54000.00")
        self._payment(contract, date(2026, 6, 15), "54000.00")  # 全额预收
        services.add_usage_record(
            usage, services.ensure_period(2026, 7), "3000.00", "7月调用量"
        )
        services.add_usage_record(
            usage, services.ensure_period(2026, 8), "2500.00", "8月调用量"
        )

    # ------------------------------------------------------------

    def _print_summary(self):
        for contract in Contract.objects.all():
            t = services.contract_totals(contract)
            self.stdout.write(
                f"{contract.number} {contract.customer}: 签约 {t['total_price']} | "
                f"开票 {t['billed']} | 收款 {t['received']} | 已确认 {t['recognized']} | "
                f"待确认 {t['pending']} | 计划 {t['planned']} | 递延 {t['deferred']}"
            )
        pend = RecognitionEntry.objects.filter(status="PENDING").count()
        self.stdout.write(f"待确认分录数: {pend}")
