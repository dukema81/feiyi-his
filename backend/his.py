# -*- coding: utf-8 -*-
"""飞医 HIS 业务内核（纯函数，无 IO 无 DB，可独立单测）"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta

# ---------------- 金额 ----------------
def money_to_cents(yuan) -> int:
    """元（可 float/str）→ 分，HALF_UP"""
    return int((Decimal(str(yuan)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def calc_rx_amount_cents(qty, price_cents) -> int:
    """处方明细金额 = 数量 × 单价（分），HALF_UP"""
    return int((Decimal(str(qty)) * Decimal(str(price_cents))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def rx_total_cents(items) -> int:
    """处方总额（分）= Σ 明细金额"""
    return sum(int(i) for i in items)

def payable_cents(total_cents, discount_rate) -> int:
    """应收 = 总额 × 折扣率，对分取整 HALF_UP（只做一次量纲转换）"""
    amt = Decimal(str(total_cents)) * Decimal(str(discount_rate))
    return int(amt.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

# ---------------- 医保 ----------------
INSURANCE_RATES = {"employee": 0.85, "resident": 0.65, "self": 1.00}

def insurance_rate(insurance_type: str) -> float:
    return INSURANCE_RATES.get(insurance_type, 1.00)

# ---------------- 状态机 ----------------
REG_TRANS = {
    "waiting": {"called", "cancelled"},
    "called": {"in_consult", "cancelled"},
    "in_consult": {"done"},
    "done": set(),
    "cancelled": set(),
}

RX_TRANS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"dispensed", "cancelled"},
    "dispensed": set(),
    "cancelled": set(),
}

PURCHASE_TRANS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"received"},
    "received": set(),
    "cancelled": set(),
}

def can_transition(trans: dict, cur: str, to: str) -> bool:
    return to in trans.get(cur, set())

# ---------------- 排班 ----------------
PERIODS = {"AM", "PM"}

def sched_conflict(existing_rows, doctor_id, sched_date, period, exclude_id=None) -> bool:
    """同医生同日期同时段冲突"""
    for r in existing_rows:
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if r["doctor_id"] == doctor_id and r["sched_date"] == sched_date and r["period"] == period:
            return True
    return False

def sched_quota_ok(quota, booked) -> bool:
    return booked < quota

# ---------------- 剂量校验 ----------------
def dose_over(dose, max_dose) -> bool:
    """单次剂量超上限（max_dose<=0 表示不限）"""
    return max_dose > 0 and dose > max_dose

# ---------------- 库存 ----------------
def fefe_batches(rows, need):
    """FEFO 分配：按效期近先出。返回 (allocations[(batch_no, take, id)], shortfall)
    rows 须含 id/batch_no/qty/expire_at"""
    batches = sorted([dict(r) for r in rows], key=lambda r: (r["expire_at"] or "9999-12-31", r["id"]))
    remain = int(need)
    allocs = []
    for b in batches:
        if remain <= 0:
            break
        have = int(b["qty"] or 0)
        if have <= 0:
            continue
        take = min(have, remain)
        allocs.append((b["id"], b["batch_no"], take))
        remain -= take
    return allocs, remain

def stock_available(rows, need) -> bool:
    _, shortfall = fefe_batches(rows, need)
    return shortfall <= 0

def low_stock_check(qty, safe_stock):
    """≤safe → (30,'warn')"""
    return (30, "warn") if qty <= safe_stock else None

def expiry_check(expire_at, days=90, today=None):
    """效期 ≤ days 天 → (25,'warn')；已过期 → (40,'risk')"""
    if not expire_at:
        return None
    today = today or date.today()
    try:
        exp = datetime.strptime(expire_at[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    left = (exp - today).days
    if left < 0:
        return (40, "risk")
    if left <= days:
        return (25, "warn")
    return None

# ---------------- 风险扫描 ----------------
def purchase_total_cents(items) -> int:
    return sum(int(i.get("qty", 0)) * int(i.get("cost_cents", 0)) for i in items)

def overdue_registration_check(created_at, hours=24, now=None):
    """挂号超时未就诊未退号 → (20,'risk')"""
    if not created_at:
        return None
    now = now or datetime.now()
    try:
        t = datetime.strptime(created_at[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    if (now - t) > timedelta(hours=hours) :
        return (20, "risk")
    return None

# ---------------- 权限 ----------------
ROLE_PERMS = {
    "admin": "*",
    "doctor": ["his.patients.*", "his.clinic.*", "his.prescriptions.*", "his.registrations.read"],
    "nurse": ["his.registrations.*", "his.patients.read", "his.schedules.read", "his.clinic.read"],
    "pharmacist": ["his.pharmacy.*", "his.inventory.read", "his.prescriptions.read", "his.drugs.read"],
    "cashier": ["his.charges.*", "his.patients.read", "his.registrations.read", "his.transactions.read"],
    "warehouse": ["his.purchases.*", "his.inventory.*", "his.suppliers.*", "his.drugs.read"],
    "reader": ["his.patients.read", "his.registrations.read", "his.prescriptions.read", "his.charges.read", "his.inventory.read", "his.schedules.read"],
}

def has_perm(perms, perm: str) -> bool:
    """perms: '*' 或逗号分隔字符串或列表；写权限含读权限"""
    if perms == "*":
        return True
    if isinstance(perms, (list, tuple)):
        parts = [str(p) for p in perms if p]
    else:
        parts = [p for p in (perms or "").split(",") if p]
    for p in parts:
        if p == perm:
            return True
        if p.endswith(".*") and perm.startswith(p[:-1]):
            return True
        if perm.endswith(".read") and (perm[:-5] + ".*") in parts:
            return True
    return False

# ---------------- 统计 ----------------
def daily_stats(regs, charges, rxs):
    """regs/charges/rxs 为当日行记录"""
    reg_total = len(regs)
    done = sum(1 for r in regs if r["status"] == "done")
    income = sum(int(c["paid_cents"] or 0) for c in charges if c["status"] == "paid")
    refund = sum(int(c["paid_cents"] or 0) for c in charges if c["status"] == "refunded")
    return {"registrations": reg_total, "consulted": done,
            "income_cents": income, "refund_cents": refund,
            "prescriptions": len(rxs)}
