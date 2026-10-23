# -*- coding: utf-8 -*-
"""飞医 HIS 纯函数内核单测（25 例）"""
import his as K
from datetime import date


# ---------- 金额 ----------
def test_money_to_cents_basic():
    assert K.money_to_cents(30) == 3000

def test_money_to_cents_round_half_up():
    assert K.money_to_cents(12.345) == 1235

def test_money_to_cents_str():
    assert K.money_to_cents("0.005") == 1

def test_calc_rx_amount():
    assert K.calc_rx_amount_cents(3, 1580) == 4740

def test_calc_rx_amount_zero():
    assert K.calc_rx_amount_cents(0, 1580) == 0

def test_rx_total():
    assert K.rx_total_cents([4740, 3200]) == 7940

def test_payable_full():
    assert K.payable_cents(9360, 1.0) == 9360

def test_payable_employee():
    assert K.payable_cents(9360, 0.85) == 7956

def test_payable_resident_rounding():
    # 1001 分 ×0.65 = 650.65 → HALF_UP 651
    assert K.payable_cents(1001, 0.65) == 651


# ---------- 医保 ----------
def test_insurance_rates():
    assert K.insurance_rate("employee") == 0.85
    assert K.insurance_rate("resident") == 0.65
    assert K.insurance_rate("self") == 1.00

def test_insurance_unknown_defaults_self():
    assert K.insurance_rate("vip") == 1.00


# ---------- 状态机 ----------
def test_reg_trans_valid():
    assert K.can_transition(K.REG_TRANS, "waiting", "called")
    assert K.can_transition(K.REG_TRANS, "called", "in_consult")
    assert K.can_transition(K.REG_TRANS, "in_consult", "done")

def test_reg_trans_invalid():
    assert not K.can_transition(K.REG_TRANS, "waiting", "done")
    assert not K.can_transition(K.REG_TRANS, "done", "cancelled")

def test_rx_trans_valid():
    assert K.can_transition(K.RX_TRANS, "draft", "submitted")
    assert K.can_transition(K.RX_TRANS, "submitted", "dispensed")
    assert not K.can_transition(K.RX_TRANS, "draft", "dispensed")

def test_purchase_trans():
    assert K.can_transition(K.PURCHASE_TRANS, "submitted", "received")
    assert not K.can_transition(K.PURCHASE_TRANS, "received", "cancelled")


# ---------- 排班 ----------
def test_sched_conflict_hit():
    rows = [{"id": 1, "doctor_id": 2, "sched_date": "2026-01-01", "period": "AM"}]
    assert K.sched_conflict(rows, 2, "2026-01-01", "AM")

def test_sched_conflict_miss():
    rows = [{"id": 1, "doctor_id": 2, "sched_date": "2026-01-01", "period": "AM"}]
    assert not K.sched_conflict(rows, 2, "2026-01-01", "PM")
    assert not K.sched_conflict(rows, 3, "2026-01-01", "AM")

def test_sched_conflict_exclude_self():
    rows = [{"id": 1, "doctor_id": 2, "sched_date": "2026-01-01", "period": "AM"}]
    assert not K.sched_conflict(rows, 2, "2026-01-01", "AM", exclude_id=1)

def test_sched_quota():
    assert K.sched_quota_ok(20, 19)
    assert not K.sched_quota_ok(20, 20)


# ---------- 剂量 ----------
def test_dose_over():
    assert K.dose_over(0.6, 0.5)
    assert not K.dose_over(0.5, 0.5)
    assert not K.dose_over(1.0, 0)  # max_dose=0 不限


# ---------- 库存 FEFO ----------
def test_fefe_order_by_expiry():
    rows = [{"id": 1, "batch_no": "A", "qty": 3, "expire_at": "2026-01-01"},
            {"id": 2, "batch_no": "B", "qty": 5, "expire_at": "2025-06-01"}]
    allocs, shortfall = K.fefe_batches(rows, 7)
    assert [a[1] for a in allocs] == ["B", "A"]
    assert shortfall == 0

def test_fefe_shortfall():
    rows = [{"id": 1, "batch_no": "A", "qty": 3, "expire_at": "2026-01-01"},
            {"id": 2, "batch_no": "B", "qty": 5, "expire_at": "2025-06-01"}]
    allocs, shortfall = K.fefe_batches(rows, 9)
    assert shortfall == 1

def test_stock_available():
    rows = [{"id": 1, "batch_no": "A", "qty": 3, "expire_at": "2026-01-01"}]
    assert K.stock_available(rows, 3)
    assert not K.stock_available(rows, 4)


# ---------- 风险规则 ----------
def test_low_stock():
    assert K.low_stock_check(8, 10) == (30, "warn")
    assert K.low_stock_check(11, 10) is None

def test_expiry_check_warn():
    near = (date.today().replace(day=1)).isoformat()
    near = (date.today() + __import__("datetime").timedelta(days=60)).isoformat()
    assert K.expiry_check(near, 90) == (25, "warn")

def test_expiry_check_far_ok():
    far = (date.today() + __import__("datetime").timedelta(days=365)).isoformat()
    assert K.expiry_check(far, 90) is None

def test_overdue_registration():
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")
    fresh = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    assert K.overdue_registration_check(old, 24) == (20, "risk")
    assert K.overdue_registration_check(fresh, 24) is None


# ---------- 权限 ----------
def test_perm_wildcard():
    assert K.has_perm("*", "his.charges.write")

def test_perm_prefix():
    assert K.has_perm("his.pharmacy.*", "his.pharmacy.read")
    assert not K.has_perm("his.pharmacy.read", "his.pharmacy.write")

def test_perm_write_not_grant_read():
    assert K.has_perm("his.charges.read", "his.charges.read")
    assert not K.has_perm("his.charges.read", "his.charges.write")


# ---------- 统计 ----------
def test_daily_stats():
    regs = [{"status": "done"}, {"status": "waiting"}]
    charges = [{"status": "paid", "paid_cents": 1000}, {"status": "refunded", "paid_cents": 200}]
    rxs = [1, 2, 3]
    s = K.daily_stats(regs, charges, rxs)
    assert s == {"registrations": 2, "consulted": 1, "income_cents": 1000, "refund_cents": 200, "prescriptions": 3}
