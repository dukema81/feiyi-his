# -*- coding: utf-8 -*-
"""飞医 HIS 冒烟测试：核心业务链路 + API 全量检查（69 项）
用法: python smoke_api.py [base_url]   默认 http://127.0.0.1:8028
幂等化：使用时间戳后缀命名动态资源，可重复执行。
"""
import sys, time, json, urllib.request, urllib.error
from decimal import Decimal, ROUND_HALF_UP

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8028"
SUF = str(int(time.time()))[-6:]
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PASS, FAIL = [], []

def req(method, path, body=None, tok=None, headers=None):
    path = urllib.parse.quote(path, safe="/?&=.%_")
    h = dict(headers or {})
    if tok:
        h["Authorization"] = "Bearer " + tok
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with OP.open(r, timeout=15) as f:
            return f.status, json.loads(f.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}

def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("OK  " if cond else "FAIL") + " " + name + ("" if cond else "  <<< " + str(detail)[:200]))

# ============ 1. 健康与认证 ============
s, j = req("GET", "/api/health")
chk("health 200", s == 200 and j["data"]["ok"], j)
s, j = req("POST", "/api/login", {"username": "admin", "password": "123456"})
chk("login admin", s == 200 and j["data"]["token"], j)
TOK = j["data"]["token"]
s, j = req("GET", "/api/me", tok=TOK)
chk("me perms", s == 200 and j["data"]["perms"], j)
s, j = req("POST", "/api/login", {"username": "nobody", "password": "x"})
chk("login bad 401", s == 401, j)
s, j = req("GET", "/api/patients")
chk("no-auth 401", s == 401, j)
s, j = req("POST", "/api/login", {"username": "reader01", "password": "123456"})
RTOK = j["data"]["token"]
s, j = req("POST", "/api/patients", {"name": "x"}, tok=RTOK)
chk("reader write 403", s == 403, j)
s, j = req("GET", "/api/dashboard", tok=TOK)
chk("dashboard", s == 200 and "registrations" in j["data"], j)

# ============ 2. 主数据 ============
s, j = req("POST", "/api/departments", {"name": "冒烟科" + SUF}, tok=TOK)
chk("dept create", s == 200, j)
DID = j["data"]["id"]
s, j = req("GET", "/api/departments", tok=TOK)
chk("dept list", s == 200 and j["data"]["total"] >= 6, j)
s, j = req("PUT", "/api/departments/%d" % DID, {"location": "9F"}, tok=TOK)
chk("dept update", s == 200, j)
s, j = req("DELETE", "/api/departments/%d" % DID, tok=TOK)
chk("dept delete", s == 200, j)
s, j = req("GET", "/api/doctors", tok=TOK)
chk("doctor list", s == 200 and j["data"]["total"] >= 5, j)
s, j = req("POST", "/api/patients", {"name": "冒烟患" + SUF, "insurance_type": "employee"}, tok=TOK)
chk("patient create", s == 200 and j["data"]["mrn"].startswith("P"), j)
PID = j["data"]["id"]
s, j = req("GET", "/api/patients?keyword=冒烟患" + SUF, tok=TOK)
chk("patient keyword", s == 200 and j["data"]["total"] >= 1, j)
s, j = req("GET", "/api/patients/%d/visits" % PID, tok=TOK)
chk("patient visits empty", s == 200 and j["data"]["total"] == 0, j)
s, j = req("POST", "/api/patients", {"name": "x", "insurance_type": "vip"}, tok=TOK)
chk("patient bad insurance 422", s == 422, j)
s, j = req("GET", "/api/drugs", tok=TOK)
chk("drug list stock", s == 200 and all("stock" in it for it in j["data"]["items"]), j)
s, j = req("GET", "/api/suppliers", tok=TOK)
chk("supplier list", s == 200 and j["data"]["total"] >= 2, j)

# ============ 3. 排班与挂号 ============
s, j = req("GET", "/api/schedules", tok=TOK)
scheds = j["data"]["items"]
chk("schedule list", s == 200 and len(scheds) >= 5, j)
SCH = [x for x in scheds if x["quota"] > x["booked"]][0]
s, j = req("POST", "/api/schedules", {"doctor_id": SCH["doctor_id"], "sched_date": SCH["sched_date"],
                                      "period": SCH["period"]}, tok=TOK)
chk("schedule conflict 422", s == 422, j)
s, j = req("POST", "/api/registrations", {"patient_id": PID, "schedule_id": SCH["id"]}, tok=TOK)
chk("registration create", s == 200 and j["data"]["no"].startswith("GH"), j)
REG = j["data"]
chk("reg fee>0", REG["fee_cents"] > 0, REG)
s, j = req("GET", "/api/registrations/queue?schedule_id=%d" % SCH["id"], tok=TOK)
chk("queue contains", s == 200 and any(i["id"] == REG["id"] for i in j["data"]["items"]), j)
s, j = req("POST", "/api/registrations/%d/transition" % REG["id"], {"action": "to_done"}, tok=TOK)
chk("reg invalid trans 422", s == 422, j)
s, j = req("POST", "/api/registrations/%d/transition" % REG["id"], {"action": "to_called"}, tok=TOK)
chk("reg called", s == 200, j)

# ============ 4. 病历 ============
s, j = req("POST", "/api/clinic-records", {"registration_id": REG["id"], "chief_complaint": "咳嗽" + SUF,
                                           "diagnosis": "上呼吸道感染", "advice": "多饮水"}, tok=TOK)
chk("record create", s == 200, j)
RID = j["data"]["id"]
s, j = req("POST", "/api/clinic-records", {"registration_id": REG["id"]}, tok=TOK)
chk("record dup 409", s == 409, j)
s, j = req("PUT", "/api/clinic-records/%d" % RID, {"advice": "复查"}, tok=TOK)
chk("record update", s == 200, j)
s, j = req("POST", "/api/registrations/%d/transition" % REG["id"], {"action": "to_in_consult"}, tok=TOK)
chk("reg in_consult", s == 200, j)

# ============ 5. 处方 ============
s, j = req("GET", "/api/inventory/summary?drug_id=1", tok=TOK)
INV_BEFORE = j["data"]["total"]
s, j = req("POST", "/api/prescriptions", {"patient_id": PID, "doctor_id": SCH["doctor_id"],
    "registration_id": REG["id"],
    "items": [{"drug_id": 1, "dose": 0.25, "frequency": "tid", "days": 3, "qty": 2},
              {"drug_id": 2, "dose": 0.9, "frequency": "bid", "days": 2, "qty": 1}]}, tok=TOK)
chk("rx create", s == 200 and j["data"]["no"].startswith("CF"), j)
RX = j["data"]
chk("rx amount", RX["total_cents"] == 2 * 1580 + 2200, RX)
chk("rx dose warning", RX["dose_warnings"] == ["布洛芬缓释胶囊"], RX)
s, j = req("POST", "/api/prescriptions/%d/transition" % RX["id"], {"action": "to_dispensed"}, tok=TOK)
chk("rx draft->dispensed 422", s == 422, j)
s, j = req("POST", "/api/prescriptions/%d/transition" % RX["id"], {"action": "to_submitted"}, tok=TOK)
chk("rx submit", s == 200, j)
s, j = req("GET", "/api/pharmacy/pending", tok=TOK)
chk("pharmacy pending", s == 200 and any(i["id"] == RX["id"] for i in j["data"]["items"]), j)
s, j = req("POST", "/api/prescriptions/%d/transition" % RX["id"], {"action": "to_dispensed"}, tok=TOK)
chk("rx dispense", s == 200 and len(j["data"]["dispensed"]) == 2, j)
s, j = req("GET", "/api/inventory/summary?drug_id=1", tok=TOK)
chk("inventory deducted", j["data"]["total"] == INV_BEFORE - 2, (INV_BEFORE, j["data"]))
s, j = req("GET", "/api/pharmacy/logs", tok=TOK)
chk("pharmacy logs", s == 200 and j["data"]["total"] >= 2, j)
s, j = req("POST", "/api/prescriptions/%d/transition" % RX["id"], {"action": "to_cancelled"}, tok=TOK)
chk("rx dispensed no cancel 422", s == 422, j)
s, j = req("POST", "/api/registrations/%d/transition" % REG["id"], {"action": "to_done"}, tok=TOK)
chk("reg done", s == 200, j)

# ============ 6. 收费 ============
s, j = req("POST", "/api/charges", {"registration_id": REG["id"], "prescription_ids": [RX["id"]],
                                    "pay_method": "wechat"}, tok=TOK)
chk("charge create", s == 200, j)
CHG = j["data"]
EXP_TOTAL = REG["fee_cents"] + RX["total_cents"]
chk("charge total", CHG["total_cents"] == EXP_TOTAL, (CHG, EXP_TOTAL))
chk("charge rate employee", CHG["discount_rate"] == 0.85, CHG)
EXP_PAID = int((Decimal(EXP_TOTAL) * Decimal("0.85")).quantize(Decimal("1"), ROUND_HALF_UP))
chk("charge paid rounding", CHG["paid_cents"] == EXP_PAID, (CHG["paid_cents"], EXP_PAID))
s, j = req("POST", "/api/charges", {"prescription_ids": [RX["id"]]}, tok=TOK)
chk("charge dup 409", s == 409, j)
s, j = req("GET", "/api/charges/%d" % CHG["id"], tok=TOK)
chk("charge detail items", s == 200 and len(j["data"]["items"]) == 2, j)
s, j = req("GET", "/api/finance/summary", tok=TOK)
chk("finance summary", s == 200 and j["data"]["income_cents"] >= CHG["paid_cents"], j)
s, j = req("GET", "/api/transactions", tok=TOK)
chk("transactions", s == 200 and j["data"]["total"] >= 1, j)

# ============ 7. 采购 ============
s, j = req("GET", "/api/inventory/summary?drug_id=6", tok=TOK)
INV6 = j["data"]["total"]
s, j = req("POST", "/api/purchases", {"supplier_id": 2, "items": [
    {"drug_id": 6, "qty": 20, "cost_cents": 600, "batch_no": "SMK" + SUF, "expiry": "2028-06-01"}]}, tok=TOK)
chk("purchase create", s == 200 and j["data"]["no"].startswith("CG"), j)
PO = j["data"]
chk("purchase total", PO["total_cents"] == 12000, PO)
s, j = req("POST", "/api/purchases/%d/transition" % PO["id"], {"action": "to_received"}, tok=TOK)
chk("purchase draft->received 422", s == 422, j)
s, j = req("POST", "/api/purchases/%d/transition" % PO["id"], {"action": "to_submitted"}, tok=TOK)
chk("purchase submit", s == 200, j)
s, j = req("POST", "/api/purchases/%d/transition" % PO["id"], {"action": "to_received"}, tok=TOK)
chk("purchase receive", s == 200, j)
s, j = req("GET", "/api/inventory/summary?drug_id=6", tok=TOK)
chk("purchase stock in", j["data"]["total"] == INV6 + 20, (INV6, j["data"]))
s, j = req("GET", "/api/suppliers", tok=TOK)
sup2 = [x for x in j["data"]["items"] if x["id"] == 2][0]
chk("supplier payable", sup2["payable_cents"] >= 12000, sup2)

# ============ 8. 风险 ============
s, j = req("POST", "/api/risks/scan", {}, tok=TOK)
chk("risk scan", s == 200 and "by_type" in j["data"], j)
s, j = req("GET", "/api/risks", tok=TOK)
chk("risk list", s == 200 and j["data"]["total"] >= 2, j)
chk("risk low_stock present", any(x["rtype"] == "drug_low_stock" for x in j["data"]["items"]), j)
chk("risk expiry present", any(x["rtype"] == "drug_expiry" for x in j["data"]["items"]), j)
chk("risk dose_over present", any(x["rtype"] == "dose_over" for x in j["data"]["items"]), j)
RISK0 = [x for x in j["data"]["items"] if x["status"] == "open"][0]
s, j = req("PUT", "/api/risks/%d/resolve" % RISK0["id"], {"note": "冒烟处理"}, tok=TOK)
chk("risk resolve", s == 200, j)

# ============ 9. 平台域 ============
s, j = req("GET", "/api/users", tok=TOK)
chk("users", s == 200 and j["data"]["total"] >= 8, j)
s, j = req("GET", "/api/notices", tok=TOK)
chk("notices", s == 200 and j["data"]["total"] >= 2, j)
s, j = req("GET", "/api/rules", tok=TOK)
chk("rules", s == 200 and any(x["name"] == "insurance_rates" for x in j["data"]["items"]), j)
s, j = req("POST", "/api/api-keys", {"name": "smoke-key-" + SUF}, tok=TOK)
chk("apikey create", s == 200 and j["data"]["key"].startswith("fys_"), j)
KEY = j["data"]["key"]
h2 = {"X-Api-Key": KEY}
s, j = req("GET", "/api/patients", headers=h2)
chk("apikey auth channel", s == 200, j)
s, j = req("GET", "/api/sync?since=0&entities=patients", tok=TOK)
chk("sync entities", s == 200 and len(j["data"]["changes"]) >= 6, j)
s, j = req("GET", "/api/sync?since=999999", tok=TOK)
chk("sync incremental empty", s == 200 and len(j["data"]["changes"]) == 0, j)
r = urllib.request.Request(BASE + "/api/export/patients", headers={"Authorization": "Bearer " + TOK})
with OP.open(r) as f:
    raw = f.read()
chk("csv export BOM", raw.startswith(b"\xef\xbb\xbf"), raw[:20])
s, j = req("GET", "/api/not-exist", tok=TOK)
chk("404 route", s == 404, j)

# ============ 汇总 ============
print("==== SMOKE PASS=%d FAIL=%d ====" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
