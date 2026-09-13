from datetime import date
from decimal import Decimal

from django.test import TestCase

from . import services
from .models import (
    AccountingPeriod,
    Contract,
    Evidence,
    Invoice,
    PerformanceObligation,
    RecognitionEntry,
)

D = Decimal


def make_contract(price="100000.00"):
    return Contract.objects.create(
        number="T-001", customer="测试客户", signed_date=date(2025, 1, 10),
        total_price=price,
    )


def add_obligation(contract, name, kind, ssp, **kw):
    return PerformanceObligation.objects.create(
        contract=contract, name=name, kind=kind, ssp=ssp, **kw
    )


class AllocationTests(TestCase):
    """分摊：合计必须等于交易价格；尾差稳定归属 SSP 最高者。"""

    def test_residual_assigned_to_highest_ssp(self):
        # 3/11、3/11、5/11 的比例产生 -0.01 尾差
        c = make_contract()
        add_obligation(c, "实施一", "IMPLEMENTATION", "30000.00")
        add_obligation(c, "实施二", "IMPLEMENTATION", "30000.00")
        sub = add_obligation(
            c, "订阅", "SUBSCRIPTION", "50000.00",
            service_start=date(2025, 1, 1), service_end=date(2025, 12, 31),
        )
        version = services.reallocate(c, "初始分摊")

        lines = {l.obligation.name: l for l in version.lines.all()}
        self.assertEqual(lines["实施一"].allocated_amount, D("27272.73"))
        self.assertEqual(lines["实施二"].allocated_amount, D("27272.73"))
        # 尾差 -0.01 稳定归属 SSP 最高的订阅义务
        self.assertEqual(lines["订阅"].allocated_amount, D("45454.54"))
        self.assertEqual(version.residual_amount, D("-0.01"))
        self.assertEqual(version.residual_obligation_id, sub.id)
        self.assertTrue(lines["订阅"].is_residual_receiver)
        total = sum(l.allocated_amount for l in version.lines.all())
        self.assertEqual(total, D("100000.00"))

    def test_reallocation_creates_new_version_and_preserves_old(self):
        c = make_contract("60000.00")
        add_obligation(
            c, "订阅", "SUBSCRIPTION", "60000.00",
            service_start=date(2025, 1, 1), service_end=date(2025, 6, 30),
        )
        v1 = services.reallocate(c, "初始分摊")
        v2 = services.reallocate(c, "条款变更重新分摊")
        self.assertEqual((v1.version_no, v2.version_no), (1, 2))
        self.assertEqual(c.allocation_versions.count(), 2)  # 旧版本保留可追溯
        # 每个确认行都能追到分配版本
        for entry in RecognitionEntry.objects.filter(obligation__contract=c):
            self.assertEqual(entry.allocation_line.version.version_no, 2)


class RecognitionTests(TestCase):
    """确认计划：订阅直线、实施看证据、按量封顶；开票不产生确认。"""

    def test_subscription_straight_line_sums_to_allocated(self):
        c = make_contract("36500.00")
        add_obligation(
            c, "订阅", "SUBSCRIPTION", "36500.00",
            service_start=date(2025, 1, 1), service_end=date(2025, 12, 31),
        )
        services.reallocate(c, "初始分摊")
        entries = RecognitionEntry.objects.filter(obligation__contract=c)
        self.assertEqual(entries.count(), 12)
        self.assertEqual(sum(e.amount for e in entries), D("36500.00"))
        jan = entries.get(period__year=2025, period__month=1)
        self.assertEqual(jan.amount, D("3100.00"))  # 31/365 天
        self.assertEqual(jan.status, "RECOGNIZED")  # 过去期间

    def test_future_subscription_entries_are_planned(self):
        c = make_contract("12000.00")
        add_obligation(
            c, "订阅", "SUBSCRIPTION", "12000.00",
            service_start=date(2027, 1, 1), service_end=date(2027, 12, 31),
        )
        services.reallocate(c, "初始分摊")
        statuses = set(
            RecognitionEntry.objects.filter(obligation__contract=c)
            .values_list("status", flat=True)
        )
        self.assertEqual(statuses, {"PLANNED"})

    def test_implementation_pending_without_evidence(self):
        c = make_contract("20000.00")
        ob = add_obligation(c, "实施", "IMPLEMENTATION", "20000.00")
        services.reallocate(c, "初始分摊")
        entry = RecognitionEntry.objects.get(obligation=ob)
        self.assertEqual(entry.status, "PENDING")
        self.assertIsNone(entry.period)

        services.add_evidence(ob, "验收报告", "YS-1", date(2026, 9, 5))
        entry.refresh_from_db()
        self.assertEqual(entry.status, "RECOGNIZED")
        self.assertEqual(entry.period.label, "2026-09")

    def test_usage_capped_at_allocated(self):
        c = make_contract("9000.00")
        ob = add_obligation(
            c, "按量", "USAGE", "9000.00", estimated_units="9000.00", unit_label="次"
        )
        services.reallocate(c, "初始分摊")
        p1 = services.ensure_period(2026, 9)
        services.add_usage_record(ob, p1, "5000.00")
        services.add_usage_record(ob, p1, "6000.00")  # 超出预计总量
        entries = RecognitionEntry.objects.filter(obligation=ob)
        self.assertEqual(sum(e.amount for e in entries), D("9000.00"))  # 封顶分摊额

    def test_invoice_does_not_create_recognition(self):
        c = make_contract("10000.00")
        add_obligation(c, "实施", "IMPLEMENTATION", "10000.00")
        services.reallocate(c, "初始分摊")
        before = RecognitionEntry.objects.count()
        Invoice.objects.create(
            contract=c, number="FP-T1", invoice_date=date(2026, 9, 1),
            amount="10000.00", period=services.ensure_period(2026, 9),
        )
        self.assertEqual(RecognitionEntry.objects.count(), before)  # 开票≠收入


class ClosedPeriodTests(TestCase):
    """关闭期间不能直接编辑。"""

    def setUp(self):
        self.c = make_contract("10000.00")
        self.ob = add_obligation(
            self.c, "订阅", "SUBSCRIPTION", "10000.00",
            service_start=date(2026, 9, 1), service_end=date(2026, 12, 31),
        )
        services.reallocate(self.c, "初始分摊")
        self.closed = services.ensure_period(2026, 9)
        services.close_period(self.closed)

    def test_close_posts_planned_entries(self):
        entry = RecognitionEntry.objects.get(period=self.closed)
        self.assertEqual(entry.status, "RECOGNIZED")

    def test_invoice_in_closed_period_rejected(self):
        with self.assertRaises(services.DomainError):
            services.assert_period_open(self.closed)

    def test_usage_in_closed_period_rejected(self):
        usage_ob = add_obligation(
            self.c, "按量", "USAGE", "1000.00", estimated_units="100.00"
        )
        with self.assertRaises(services.DomainError):
            services.add_usage_record(usage_ob, self.closed, "10.00")

    def test_evidence_in_closed_period_rejected(self):
        impl = add_obligation(self.c, "实施", "IMPLEMENTATION", "5000.00")
        with self.assertRaises(services.DomainError):
            services.add_evidence(impl, "验收", "YS-X", date(2026, 9, 10))

    def test_reallocate_blocked_by_frozen_entries(self):
        with self.assertRaises(services.DomainError):
            services.reallocate(self.c, "试图重分摊")

    def test_double_close_rejected(self):
        with self.assertRaises(services.DomainError):
            services.close_period(self.closed)


class ReconciliationTests(TestCase):
    """递延对照：期初 + 开票 − 确认 = 期末，逐期连续。"""

    def test_reconciliation_identity(self):
        c = make_contract("36500.00")
        add_obligation(
            c, "订阅", "SUBSCRIPTION", "36500.00",
            service_start=date(2025, 1, 1), service_end=date(2025, 12, 31),
        )
        services.reallocate(c, "初始分摊")
        Invoice.objects.create(
            contract=c, number="FP-R1", invoice_date=date(2025, 1, 5),
            amount="36500.00", period=services.ensure_period(2025, 1),
        )
        rows = services.contract_reconciliation(c)
        self.assertEqual(rows[0]["opening"], D("0.00"))
        prev_closing = D("0.00")
        for row in rows:
            self.assertEqual(row["opening"], prev_closing)
            self.assertEqual(
                row["closing"], row["opening"] + row["billed"] - row["recognized"]
            )
            prev_closing = row["closing"]
        self.assertEqual(rows[-1]["closing"], D("0.00"))  # 年末递延清零

    def test_totals_split_signed_received_recognized(self):
        c = make_contract("10000.00")
        add_obligation(c, "实施", "IMPLEMENTATION", "10000.00")
        services.reallocate(c, "初始分摊")
        Invoice.objects.create(
            contract=c, number="FP-R2", invoice_date=date(2026, 9, 1),
            amount="6000.00", period=services.ensure_period(2026, 9),
        )
        t = services.contract_totals(c)
        self.assertEqual(t["total_price"], D("10000.00"))  # 签了
        self.assertEqual(t["billed"], D("6000.00"))        # 开了
        self.assertEqual(t["recognized"], D("0.00"))       # 未验收不确认
        self.assertEqual(t["pending"], D("10000.00"))      # 待确认
        self.assertEqual(t["deferred"], D("6000.00"))      # 已开票未确认
