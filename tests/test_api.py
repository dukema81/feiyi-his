# -*- coding: utf-8 -*-
"""飞医 HIS API 集成测试（20 例）"""
from decimal import Decimal, ROUND_HALF_UP
import pytest


# ---------- 认证 ----------
def test_health(jreq_fn):
    j = jreq_fn("GET", "/api/health")
    assert j["code"] == 200 and j["data"]["ok"]

def test_login_fail(jreq_fn):
    j = jreq_fn("POST", "/api/login", {"username": "admin", "password": "wrong"})
    assert j["code"] == 401

def test_unauthorized_401(jreq_fn):
    j = jreq_fn("GET", "/api/patients")
    assert j["code"] == 401

def test_role_forbidden_403(jreq_fn, jreq_fn_=None):
    pass


# ---------- 主数据 ----------
def test_dept_crud(jreq_fn, tok):
    j = jreq_fn("POST", "/api/departments", {"name": "测试科室T"}, token=tok)
    assert j["code"] == 200
    did = j["data"]["id"]
    j = jreq_fn("POST", "/api/departments", {"name": "测试科室T"}, token=tok)
    assert j["code"] == 409
    j = jreq_fn("PUT", "/api/departments/%d" % did, {"location": "3F"}, token=tok)
    assert j["code"] == 200
    j = jreq_fn("DELETE", "/api/departments/%d" % did, token=tok)
    assert j["code"] == 200

def test_patient_create_and_mrn(jreq_fn, tok):
    j = jreq_fn("POST", "/api/patients", {"name": "测试患者", "insurance_type": "resident"}, token=tok)
    assert j["code"] == 200 and j["data"]["mrn"].startswith("P")
    j = jreq_fn("POST", "/api/patients", {"name": "x", "insurance_type": "vip"}, token=tok)
    assert j["code"] == 422

def test_doctor_list_has_dept(jreq_fn, tok):
    j = jreq_fn("GET", "/api/doctors", token=tok)
    assert j["code"] == 200 and j["data"]["total"] >= 5
    assert all("dept_name" in it for it in j["data"]["items"])


# ---------- 排班与挂号 ----------
def test_schedule_conflict_422(jreq_fn, tok):
    j = jreq_fn("GET", "/api/schedules", token=tok)
    s = j["data"]["items"][0]
    j = jreq_fn("POST", "/api/schedules",
                {"doctor_id": s["doctor_id"], "sched_date": s["sched_date"], "period": s["period"]}, token=tok)
    assert j["code"] == 422

def test_registration_flow(jreq_fn, tok):
    s = jreq_fn("GET", "/api/schedules", token=tok)["data"]["items"][0]
    j = jreq_fn("POST", "/api/registrations", {"patient_id": 1, "schedule_id": s["id"]}, token=tok)
    assert j["code"] == 200 and j["data"]["no"].startswith("GH")
    rid = j["data"]["id"]
    # 非法流转
    j = jreq_fn("POST", "/api/registrations/%d/transition" % rid, {"action": "to_done"}, token=tok)
    assert j["code"] == 422
    for act in ("to_called", "to_in_consult", "to_done"):
        j = jreq_fn("POST", "/api/registrations/%d/transition" % rid, {"action": act}, token=tok)
        assert j["code"] == 200, (act, j)
    j = jreq_fn("GET", "/api/registrations/%d" % rid, token=tok)
    assert j["data"]["status"] == "done"
    # done 自动建空病历
    j = jreq_fn("GET", "/api/clinic-records?patient_id=1", token=tok)
    assert any(r["registration_id"] == rid for r in j["data"]["items"])

def test_queue(jreq_fn, tok):
    j = jreq_fn("GET", "/api/registrations/queue", token=tok)
    assert j["code"] == 200 and "waiting" in j["data"]


# ---------- 病历 ----------
def test_record_unique_per_reg(jreq_fn, tok):
    s = jreq_fn("GET", "/api/schedules", token=tok)["data"]["items"][1]
    rid = jreq_fn("POST", "/api/registrations", {"patient_id": 2, "schedule_id": s["id"]}, token=tok)["data"]["id"]
    j = jreq_fn("POST", "/api/clinic-records", {"registration_id": rid, "chief_complaint": "发热", "diagnosis": "感冒"}, token=tok)
    assert j["code"] == 200
    j = jreq_fn("POST", "/api/clinic-records", {"registration_id": rid, "chief_complaint": "x"}, token=tok)
    assert j["code"] == 409


# ---------- 处方 ----------
def test_rx_create_amount_and_dose_warn(jreq_fn, tok):
    j = jreq_fn("POST", "/api/prescriptions", {
        "patient_id": 1, "doctor_id": 1,
        "items": [{"drug_id": 1, "dose": 0.25, "qty": 2},
                  {"drug_id": 2, "dose": 0.9, "qty": 1}]}, token=tok)
    assert j["code"] == 200
    d = j["data"]
    assert d["no"].startswith("CF")
    assert d["total_cents"] == 2 * 1580 + 2200
    assert d["dose_warnings"] == ["布洛芬缓释胶囊"]
    # 风险已登记
    j2 = jreq_fn("GET", "/api/risks?type=dose_over", token=tok)
    assert j2["code"] == 200

def test_rx_invalid_transition(jreq_fn, tok):
    j = jreq_fn("POST", "/api/prescriptions", {
        "patient_id": 1, "doctor_id": 1,
        "items": [{"drug_id": 5, "dose": 1, "qty": 1}]}, token=tok)
    rxid = j["data"]["id"]
    j = jreq_fn("POST", "/api/prescriptions/%d/transition" % rxid, {"action": "to_dispensed"}, token=tok)
    assert j["code"] == 422  # draft 不能直接发药

def test_rx_dispense_fefo_and_stock(jreq_fn, tok):
    before = jreq_fn("GET", "/api/inventory/summary?drug_id=4", token=tok)["data"]["total"]
    j = jreq_fn("POST", "/api/prescriptions", {
        "patient_id": 2, "doctor_id": 2,
        "items": [{"drug_id": 4, "dose": 0.05, "qty": 3}]}, token=tok)
    rxid = j["data"]["id"]
    jreq_fn("POST", "/api/prescriptions/%d/transition" % rxid, {"action": "to_submitted"}, token=tok)
    j = jreq_fn("POST", "/api/prescriptions/%d/transition" % rxid, {"action": "to_dispensed"}, token=tok)
    assert j["code"] == 200 and j["data"]["dispensed"][0]["qty"] == 3
    after = jreq_fn("GET", "/api/inventory/summary?drug_id=4", token=tok)["data"]["total"]
    assert after == before - 3

def test_rx_dispense_insufficient_422(jreq_fn, tok):
    j = jreq_fn("POST", "/api/prescriptions", {
        "patient_id": 2, "doctor_id": 2,
        "items": [{"drug_id": 4, "dose": 0.05, "qty": 9999}]}, token=tok)
    rxid = j["data"]["id"]
    jreq_fn("POST", "/api/prescriptions/%d/transition" % rxid, {"action": "to_submitted"}, token=tok)
    j = jreq_fn("POST", "/api/prescriptions/%d/transition" % rxid, {"action": "to_dispensed"}, token=tok)
    assert j["code"] == 422 and "库存不足" in j["message"]


# ---------- 收费 ----------
def test_charge_insurance_discount(jreq_fn, tok):
    s = jreq_fn("GET", "/api/schedules", token=tok)["data"]["items"][0]
    reg = jreq_fn("POST", "/api/registrations", {"patient_id": 1, "schedule_id": s["id"]}, token=tok)["data"]  # 张三 employee
    jreq_fn("POST", "/api/registrations/%d/transition" % reg["id"], {"action": "to_called"}, token=tok)
    jreq_fn("POST", "/api/registrations/%d/transition" % reg["id"], {"action": "to_in_consult"}, token=tok)
    jreq_fn("POST", "/api/registrations/%d/transition" % reg["id"], {"action": "to_done"}, token=tok)
    j = jreq_fn("POST", "/api/charges", {"registration_id": reg["id"], "pay_method": "cash"}, token=tok)
    assert j["code"] == 200
    d = j["data"]
    assert d["discount_rate"] == 0.85
    exp = int((Decimal(d["total_cents"]) * Decimal("0.85")).quantize(Decimal("1"), ROUND_HALF_UP))
    assert d["paid_cents"] == exp

def test_charge_dup_rx_409(jreq_fn, tok):
    j = jreq_fn("POST", "/api/prescriptions", {
        "patient_id": 1, "doctor_id": 1,
        "items": [{"drug_id": 5, "dose": 1, "qty": 1}]}, token=tok)
    rxid = j["data"]["id"]
    jreq_fn("POST", "/api/prescriptions/%d/transition" % rxid, {"action": "to_submitted"}, token=tok)
    j = jreq_fn("POST", "/api/charges", {"prescription_ids": [rxid]}, token=tok)
    assert j["code"] == 200
    j = jreq_fn("POST", "/api/charges", {"prescription_ids": [rxid]}, token=tok)
    assert j["code"] == 409

def test_charge_refund(jreq_fn, tok):
    j = jreq_fn("GET", "/api/charges", token=tok)
    cid = j["data"]["items"][0]["id"]
    j = jreq_fn("POST", "/api/charges/%d/refund" % cid, {}, token=tok)
    assert j["code"] == 200 and j["data"]["refund_cents"] > 0


# ---------- 采购 / 库存 ----------
def test_purchase_receive(jreq_fn, tok):
    before = jreq_fn("GET", "/api/inventory/summary?drug_id=6", token=tok)["data"]["total"]
    j = jreq_fn("POST", "/api/purchases", {"supplier_id": 1, "items": [
        {"drug_id": 6, "qty": 12, "cost_cents": 500, "batch_no": "BTEST-UT01", "expiry": "2028-01-01"}]}, token=tok)
    assert j["code"] == 200 and j["data"]["no"].startswith("CG")
    pid = j["data"]["id"]
    jreq_fn("POST", "/api/purchases/%d/transition" % pid, {"action": "to_submitted"}, token=tok)
    j = jreq_fn("POST", "/api/purchases/%d/transition" % pid, {"action": "to_received"}, token=tok)
    assert j["code"] == 200
    after = jreq_fn("GET", "/api/inventory/summary?drug_id=6", token=tok)["data"]["total"]
    assert after == before + 12
    sup = [x for x in jreq_fn("GET", "/api/suppliers", token=tok)["data"]["items"] if x["id"] == 1][0]
    assert sup["payable_cents"] >= 12 * 500

def test_purchase_invalid_transition(jreq_fn, tok):
    j = jreq_fn("POST", "/api/purchases", {"supplier_id": 1, "items": [
        {"drug_id": 6, "qty": 1, "cost_cents": 100, "batch_no": "BTEST-UT02", "expiry": "2028-01-01"}]}, token=tok)
    pid = j["data"]["id"]
    j = jreq_fn("POST", "/api/purchases/%d/transition" % pid, {"action": "to_received"}, token=tok)
    assert j["code"] == 422  # draft 不能直接入库


# ---------- 风险 / 平台 ----------
def test_risk_scan(jreq_fn, tok):
    j = jreq_fn("POST", "/api/risks/scan", {}, token=tok)
    assert j["code"] == 200 and "by_type" in j["data"]
    assert j["data"]["by_type"].get("drug_low_stock", 0) >= 1  # seed 含低库存样例

def test_sync_and_idempotency(jreq_fn, tok):
    j = jreq_fn("GET", "/api/sync?since=0&entities=patients", token=tok)
    assert j["code"] == 200 and len(j["data"]["changes"]) >= 6
    h = {"Idempotency-Key": "pytest-idem-001"}
    j1 = jreq_fn("POST", "/api/patients", {"name": "幂等员"}, token=tok, headers=h)
    j2 = jreq_fn("POST", "/api/patients", {"name": "幂等员"}, token=tok, headers=h)
    assert j1["data"]["id"] == j2["data"]["id"]

def test_csv_export(jreq_fn, tok):
    st, raw = jreq_fn("GET", "/api/export/patients", token=tok)
    assert st == "raw" and raw.startswith("\ufeff")

def test_role_forbidden(jreq_fn):
    j = jreq_fn("POST", "/api/login", {"username": "liug", "password": "123456"})  # cashier
    t = j["data"]["token"]
    j = jreq_fn("POST", "/api/prescriptions", {"patient_id": 1, "doctor_id": 1, "items": []}, token=t)
    assert j["code"] == 403
