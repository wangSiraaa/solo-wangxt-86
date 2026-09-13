"""核算引擎：交易价格分摊 + 确认计划生成。

示例政策（仅用于本项目演示，不宣称覆盖所有会计准则）：
1. 合同交易价格按各履约义务独立售价(SSP)占比分摊；
2. 分摊尾差稳定归属独立售价最高的履约义务（并列取 id 最小者）；
3. 订阅按服务期日历天直线确认；实施以验收证据为确认时点，无证据保持待确认；
   按量按实际用量 × (分摊额/预计总量) 确认，累计不超过分摊额；
4. 开票与收款只影响应收/递延，不产生确认记录；
5. 已关闭期间内的记录冻结，不能直接编辑。
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import (
    AccountingPeriod,
    AllocationLine,
    AllocationVersion,
    Contract,
    Evidence,
    PerformanceObligation,
    RecognitionEntry,
    UsageRecord,
)

CENT = Decimal("0.01")
RATIO_PLACES = Decimal("0.0000000001")


class DomainError(Exception):
    """业务规则错误，视图层转换为 400。"""


def q2(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- 期间

def ensure_period(year: int, month: int) -> AccountingPeriod:
    period, _ = AccountingPeriod.objects.get_or_create(year=year, month=month)
    return period


def period_for(d: date) -> AccountingPeriod:
    return ensure_period(d.year, d.month)


def current_period() -> AccountingPeriod:
    today = timezone.localdate()
    return ensure_period(today.year, today.month)


def assert_period_open(period: AccountingPeriod):
    if period.is_closed:
        raise DomainError(f"期间 {period.label} 已关闭，不能直接编辑")


def entry_status_for(period: AccountingPeriod) -> str:
    cur = current_period()
    if (period.year, period.month) <= (cur.year, cur.month):
        return RecognitionEntry.Status.RECOGNIZED
    return RecognitionEntry.Status.PLANNED


def month_slices(start: date, end: date):
    """[start, end] 按自然月切片，返回 [(year, month, days)]。"""
    slices = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        last_day = calendar.monthrange(y, m)[1]
        lo = max(start, date(y, m, 1))
        hi = min(end, date(y, m, last_day))
        slices.append((y, m, (hi - lo).days + 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return slices


# ---------------------------------------------------------------- 分摊

@transaction.atomic
def reallocate(contract: Contract, reason: str) -> AllocationVersion:
    """生成新的分配版本并重建该合同全部确认计划。

    旧版本与其分配行保留作审计追溯；确认记录引用所属分配行，
    因此任何金额都能追到具体分配版本。
    """
    obligations = list(contract.obligations.order_by("id"))
    if not obligations:
        raise DomainError("合同没有履约义务，无法分摊")

    if RecognitionEntry.objects.filter(
        obligation__contract=contract, period__is_closed=True
    ).exists():
        raise DomainError("该合同存在已关闭期间的确认记录，期间已冻结，不能重新分摊")

    RecognitionEntry.objects.filter(obligation__contract=contract).delete()

    total_ssp = sum(Decimal(str(o.ssp)) for o in obligations)
    if total_ssp <= 0:
        raise DomainError("独立售价合计必须为正数")

    price = q2(contract.total_price)
    version = AllocationVersion.objects.create(
        contract=contract,
        version_no=contract.allocation_versions.count() + 1,
        reason=reason,
        total_price=price,
        total_ssp=total_ssp,
        residual_amount=Decimal("0.00"),
    )

    # 尾差归属规则固定：SSP 最高者优先，并列取 id 最小 —— 归属稳定、可复算
    residual_target = sorted(obligations, key=lambda o: (-o.ssp, o.id))[0]

    lines = {}
    allocated_sum = Decimal("0.00")
    for o in obligations:
        ratio = Decimal(o.ssp) / Decimal(total_ssp)
        amount = q2(price * ratio)
        line = AllocationLine.objects.create(
            version=version,
            obligation=o,
            ssp=o.ssp,
            ratio=ratio.quantize(RATIO_PLACES),
            allocated_amount=amount,
            is_residual_receiver=(o.id == residual_target.id),
        )
        lines[o.id] = line
        allocated_sum += amount

    residual = price - allocated_sum
    if residual != Decimal("0.00"):
        target = lines[residual_target.id]
        target.allocated_amount += residual
        target.save(update_fields=["allocated_amount"])
        version.residual_amount = residual
        version.residual_obligation = residual_target
        version.save(update_fields=["residual_amount", "residual_obligation"])

    for o in obligations:
        _generate_entries(o, lines[o.id])
    return version


def _generate_entries(obligation: PerformanceObligation, line: AllocationLine):
    kind = obligation.kind
    if kind == PerformanceObligation.Kind.SUBSCRIPTION:
        _generate_subscription_entries(obligation, line)
    elif kind == PerformanceObligation.Kind.IMPLEMENTATION:
        _generate_implementation_entry(obligation, line)
    elif kind == PerformanceObligation.Kind.USAGE:
        _generate_usage_entries(obligation, line)
    else:  # pragma: no cover
        raise DomainError(f"未知义务类型 {kind}")


def _generate_subscription_entries(obligation, line):
    """订阅：服务期内按日历天直线分摊；最后一期兜底尾差，保证合计=分摊额。"""
    start, end = obligation.service_start, obligation.service_end
    if not start or not end or end < start:
        raise DomainError(f"订阅型义务「{obligation.name}」缺少有效服务期")
    total_days = (end - start).days + 1
    slices = month_slices(start, end)
    accumulated = Decimal("0.00")
    for i, (y, m, days) in enumerate(slices):
        period = ensure_period(y, m)
        if i < len(slices) - 1:
            amount = q2(line.allocated_amount * days / total_days)
            accumulated += amount
        else:
            amount = line.allocated_amount - accumulated
        RecognitionEntry.objects.create(
            obligation=obligation,
            allocation_line=line,
            period=period,
            amount=amount,
            status=entry_status_for(period),
            source=RecognitionEntry.Source.SUBSCRIPTION_SCHEDULE,
            note=f"直线分摊 {days}/{total_days} 天",
        )


def _generate_implementation_entry(obligation, line):
    """实施：一次性确认，以验收证据日期所在期间为确认期间；无证据保持待确认。"""
    evidence = getattr(obligation, "evidence", None)
    if evidence is not None:
        period, status = evidence.period, entry_status_for(evidence.period)
        note = f"验收单 {evidence.reference}"
    else:
        period, status = None, RecognitionEntry.Status.PENDING
        note = "待验收证据"
    RecognitionEntry.objects.create(
        obligation=obligation,
        allocation_line=line,
        period=period,
        amount=line.allocated_amount,
        status=status,
        source=RecognitionEntry.Source.IMPLEMENTATION_ACCEPTANCE,
        note=note,
    )


def _generate_usage_entries(obligation, line):
    """按量：实际用量 × 单价(分摊额/预计总量)，累计封顶分摊额。"""
    if not obligation.estimated_units or obligation.estimated_units <= 0:
        raise DomainError(f"按量型义务「{obligation.name}」缺少预计总量")
    rate = line.allocated_amount / Decimal(str(obligation.estimated_units))
    recognized = Decimal("0.00")
    records = obligation.usage_records.order_by("period__year", "period__month", "id")
    for rec in records:
        amount = _usage_amount(line, rec, rate, recognized)
        if amount <= 0:
            break
        recognized += amount
        RecognitionEntry.objects.create(
            obligation=obligation,
            allocation_line=line,
            period=rec.period,
            amount=amount,
            status=entry_status_for(rec.period),
            source=RecognitionEntry.Source.USAGE,
            note=f"用量 {rec.quantity}{obligation.unit_label}",
        )


def _usage_amount(line, record, rate, recognized_so_far) -> Decimal:
    remaining = line.allocated_amount - recognized_so_far
    if remaining <= 0:
        return Decimal("0.00")
    return min(q2(rate * Decimal(str(record.quantity))), remaining)


# ---------------------------------------------------------------- 业务动作

def _current_line(obligation) -> AllocationLine:
    line = (
        AllocationLine.objects.filter(
            obligation=obligation, version__contract=obligation.contract
        )
        .order_by("-version__version_no")
        .first()
    )
    if line is None:
        raise DomainError("合同尚未分摊，请先创建分配版本")
    return line


@transaction.atomic
def add_evidence(obligation, title, reference, accepted_date, note="") -> Evidence:
    if obligation.kind != PerformanceObligation.Kind.IMPLEMENTATION:
        raise DomainError("只有实施类义务需要验收证据")
    if hasattr(obligation, "evidence"):
        raise DomainError("该义务已存在验收证据")
    period = period_for(accepted_date)
    assert_period_open(period)
    evidence = Evidence.objects.create(
        obligation=obligation,
        title=title,
        reference=reference,
        accepted_date=accepted_date,
        period=period,
        note=note,
    )
    entry = obligation.recognition_entries.filter(
        source=RecognitionEntry.Source.IMPLEMENTATION_ACCEPTANCE,
        status=RecognitionEntry.Status.PENDING,
    ).get()
    entry.period = period
    entry.status = entry_status_for(period)
    entry.note = f"验收单 {reference}"
    entry.save(update_fields=["period", "status", "note"])
    return evidence


@transaction.atomic
def remove_evidence(evidence: Evidence):
    assert_period_open(evidence.period)
    obligation = evidence.obligation
    entry = obligation.recognition_entries.filter(
        source=RecognitionEntry.Source.IMPLEMENTATION_ACCEPTANCE
    ).get()
    entry.period = None
    entry.status = RecognitionEntry.Status.PENDING
    entry.note = "待验收证据"
    entry.save(update_fields=["period", "status", "note"])
    evidence.delete()


@transaction.atomic
def add_usage_record(obligation, period, quantity, note="") -> UsageRecord:
    if obligation.kind != PerformanceObligation.Kind.USAGE:
        raise DomainError("只有按量类义务可以登记用量")
    assert_period_open(period)
    record = UsageRecord.objects.create(
        obligation=obligation, period=period, quantity=quantity, note=note
    )
    line = _current_line(obligation)
    recognized = sum(
        e.amount
        for e in obligation.recognition_entries.filter(source=RecognitionEntry.Source.USAGE)
    )
    rate = line.allocated_amount / Decimal(str(obligation.estimated_units))
    amount = _usage_amount(line, record, rate, recognized)
    if amount > 0:
        RecognitionEntry.objects.create(
            obligation=obligation,
            allocation_line=line,
            period=period,
            amount=amount,
            status=entry_status_for(period),
            source=RecognitionEntry.Source.USAGE,
            note=f"用量 {record.quantity}{obligation.unit_label}",
        )
    return record


@transaction.atomic
def remove_usage_record(record: UsageRecord):
    """删除用量记录并按剩余记录重建该义务的按量确认（已关闭期间冻结）。"""
    obligation = record.obligation
    assert_period_open(record.period)
    entries = obligation.recognition_entries.filter(source=RecognitionEntry.Source.USAGE)
    if entries.filter(period__is_closed=True).exists():
        raise DomainError("该义务存在已关闭期间的按量确认，不能删除用量记录")
    entries.delete()
    record.delete()
    line = _current_line(obligation)
    _generate_usage_entries(obligation, line)


@transaction.atomic
def close_period(period: AccountingPeriod):
    if period.is_closed:
        raise DomainError(f"期间 {period.label} 已是关闭状态")
    RecognitionEntry.objects.filter(
        period=period, status=RecognitionEntry.Status.PLANNED
    ).update(status=RecognitionEntry.Status.RECOGNIZED)
    period.is_closed = True
    period.closed_at = timezone.now()
    period.save(update_fields=["is_closed", "closed_at"])


# ---------------------------------------------------------------- 对照表

def contract_reconciliation(contract: Contract):
    """逐期递延对照：期初递延 + 当期开票 − 当期确认 = 期末递延。

    收款单列展示（现金口径，不参与递延计算）；计划/待确认单列，
    不冲减递延。任何一行确认金额都可经 allocation_line 追到分配版本。
    """
    cur = current_period()
    entries = list(
        RecognitionEntry.objects.filter(obligation__contract=contract)
        .select_related("period", "allocation_line__version")
    )
    invoices = list(contract.invoices.select_related("period"))
    payments = list(contract.payments.select_related("period"))

    keys = set()
    for coll, attr in ((invoices, "period"), (payments, "period")):
        for obj in coll:
            keys.add((obj.period.year, obj.period.month))
    for e in entries:
        if e.period_id:
            keys.add((e.period.year, e.period.month))
    if not keys:
        return []
    first = min(keys)
    last = max(max(keys), (cur.year, cur.month))

    periods = {
        (p.year, p.month): p
        for p in AccountingPeriod.objects.filter(year__gte=first[0])
        if (p.year, p.month) >= first and (p.year, p.month) <= last
    }

    rows = []
    deferred = Decimal("0.00")
    for key in sorted(periods):
        period = periods[key]
        billed = sum(i.amount for i in invoices if (i.period.year, i.period.month) == key)
        received = sum(p.amount for p in payments if (p.period.year, p.period.month) == key)
        recognized = sum(
            e.amount
            for e in entries
            if e.period_id
            and (e.period.year, e.period.month) == key
            and e.status == RecognitionEntry.Status.RECOGNIZED
        )
        planned = sum(
            e.amount
            for e in entries
            if e.period_id
            and (e.period.year, e.period.month) == key
            and e.status == RecognitionEntry.Status.PLANNED
        )
        opening = deferred
        closing = opening + billed - recognized
        deferred = closing
        rows.append(
            {
                "period": period.label,
                "is_closed": period.is_closed,
                "opening": opening,
                "billed": billed,
                "received": received,
                "recognized": recognized,
                "planned": planned,
                "closing": closing,
            }
        )
    return rows


def contract_totals(contract: Contract) -> dict:
    entries = list(RecognitionEntry.objects.filter(obligation__contract=contract))
    recognized = sum(
        e.amount for e in entries if e.status == RecognitionEntry.Status.RECOGNIZED
    )
    planned = sum(e.amount for e in entries if e.status == RecognitionEntry.Status.PLANNED)
    pending = sum(e.amount for e in entries if e.status == RecognitionEntry.Status.PENDING)
    billed = sum(i.amount for i in contract.invoices.all())
    received = sum(p.amount for p in contract.payments.all())
    total_price = q2(contract.total_price)
    return {
        "total_price": total_price,
        "billed": billed,
        "received": received,
        "recognized": recognized,
        "planned": planned,
        "pending": pending,
        "deferred": billed - recognized,
        "unbilled": total_price - billed,
    }
