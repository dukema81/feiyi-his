# -*- coding: utf-8 -*-
"""飞医 HIS 服务端：零依赖 HTTP API（端口 8028，前缀可配）"""
import os, re, json, time, hashlib, traceback, urllib.parse, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http import cookies as http_cookies

import db as D
from db import q, q1, execute, next_seq, make_no, bump_sync, get_sync
import his as K
import seed as S

PORT = int(os.environ.get("HIS_PORT", "8028"))
PREFIX = os.environ.get("HIS_PREFIX", "")
TOKEN_TTL = 7 * 86400

def now_s():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def jdump(o):
    return json.dumps(o, ensure_ascii=False, default=str)

class ApiError(Exception):
    def __init__(self, code, message):
        self.code = code; self.message = message

def page_args(qs):
    p = max(int(qs.get("page", ["1"])[0] or 1), 1)
    s = min(max(int(qs.get("size", ["20"])[0] or 20), 1), 200)
    return p, s, (p - 1) * s

def listwrap(sql, params, qs, extra=None):
    p, s, off = page_args(qs)
    total = q1("SELECT COUNT(*) AS c FROM (" + sql + ")", params)["c"]
    rows = q(sql + " LIMIT %d OFFSET %d" % (s, off), params)
    items = [dict(r) for r in rows]
    if extra:
        for it in items:
            extra(it)
    return {"items": items, "total": total, "page": p, "size": s}

def csv_export(rows, cols):
    import io, csv as _csv
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] if c in r.keys() else "" for c in cols])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")

def log_act(user_id, action, detail=""):
    D.execute("INSERT INTO logs(ts,user_id,action,detail) VALUES(?,?,?,?)", (now_s(), user_id, action, detail))

# ---------- 认证 ----------

def auth_token(tok):
    if not tok:
        return None
    row = q1("SELECT t.*, u.username, u.name, u.role FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?", (tok,))
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < now_s():
        execute("DELETE FROM tokens WHERE token=?", (tok,))
        return None
    return row

def auth_key(key):
    if not key:
        return None
    row = q1("SELECT * FROM api_keys WHERE key_hash=? AND status=1", (sha(key),))
    if not row:
        return None
    execute("UPDATE api_keys SET last_used=? WHERE id=?", (now_s(), row["id"]))
    return {"username": "apikey:" + (row["prefix"] or "k"), "name": row["name"], "role": "apikey", "perms": (row["perms"] or "his.read").split(",")}

def do_login(body):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    u = q1("SELECT * FROM users WHERE username=? AND status=1", (username,))
    if not u or u["password"] != sha(password):
        log_act(None, "login_fail", username)
        raise ApiError(401, "用户名或密码错误")
    tok = sha(username + str(time.time()) + os.urandom(8).hex())[:40]
    exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + TOKEN_TTL))
    execute("INSERT INTO tokens(token, user_id, created_at, expires_at) VALUES(?,?,?,?)", (tok, u["id"], now_s(), exp))
    log_act(u["id"], "login", username)
    perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"])
    return {"token": tok, "expires_at": exp, "user": {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"]}, "perms": perms}

def h_login(ctx, m, qs, body):
    return do_login(body)

def h_logout(ctx, m, qs, body):
    execute("DELETE FROM tokens WHERE token=?", (ctx["token"],))
    return {"ok": True}

def h_me(ctx, m, qs, body):
    u = ctx["user"]
    perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"]) if u.get("role") != "apikey" else u["perms"]
    return {"user": {"id": u.get("id"), "username": u["username"], "name": u["name"], "role": u["role"]}, "perms": perms}

def h_health(ctx, m, qs, body):
    return {"ok": True, "service": "feiyi-his", "ts": now_s()}

# ---------- 用户 / Key ----------

def h_users(ctx, m, qs, body):
    return listwrap("SELECT id,username,name,role,phone,status,created_at FROM users ORDER BY id", (), qs)

def h_users_create(ctx, m, qs, body):
    if not body.get("username") or not body.get("password"):
        raise ApiError(422, "username/password 必填")
    if q1("SELECT id FROM users WHERE username=?", (body["username"],)):
        raise ApiError(409, "用户名已存在")
    role = body.get("role", "reader")
    if role not in K.ROLE_PERMS:
        raise ApiError(422, "角色非法")
    c = execute("INSERT INTO users(username,password,name,role,phone) VALUES(?,?,?,?,?)",
                (body["username"], sha(body["password"]), body.get("name", body["username"]), role, body.get("phone")))
    return {"id": c.lastrowid}

def h_users_update(ctx, m, qs, body):
    uid = int(m.group(1))
    if not q1("SELECT id FROM users WHERE id=?", (uid,)):
        raise ApiError(404, "用户不存在")
    sets, params = [], []
    for f in ("name", "role", "phone"):
        if f in body:
            if f == "role" and body[f] not in K.ROLE_PERMS:
                raise ApiError(422, "角色非法")
            sets.append(f + "=?"); params.append(body[f])
    if body.get("password"):
        sets.append("password=?"); params.append(sha(body["password"]))
    if "status" in body:
        sets.append("status=?"); params.append(1 if body["status"] else 0)
    if sets:
        params.append(uid)
        execute("UPDATE users SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_keys(ctx, m, qs, body):
    return listwrap("SELECT id,name,prefix,perms,status,last_used,created_at FROM api_keys ORDER BY id", (), qs)

def h_keys_create(ctx, m, qs, body):
    name = body.get("name") or "default"
    raw = "fys_" + sha(name + str(time.time()) + os.urandom(8).hex())[:32]
    c = execute("INSERT INTO api_keys(name, key_hash, prefix, perms) VALUES(?,?,?,?)",
                (name, sha(raw), raw[:12], body.get("perms", "his.*")))
    return {"id": c.lastrowid, "key": raw, "note": "仅此一次返回明文，请妥善保存"}

def h_keys_delete(ctx, m, qs, body):
    execute("DELETE FROM api_keys WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

# ---------- 科室 ----------

def h_dept_list(ctx, m, qs, body):
    kw = qs.get("keyword", [""])[0]
    cond, params = "1=1", []
    if kw:
        cond = "(name LIKE ? OR location LIKE ?)"; params = ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM departments WHERE " + cond + " ORDER BY id", params, qs)

def h_dept_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    if q1("SELECT id FROM departments WHERE name=?", (body["name"],)):
        raise ApiError(409, "科室名已存在")
    c = execute("INSERT INTO departments(name,location,remark) VALUES(?,?,?)",
                (body["name"], body.get("location"), body.get("remark")))
    bump_sync("departments")
    return {"id": c.lastrowid}

def h_dept_update(ctx, m, qs, body):
    did = int(m.group(1))
    if not q1("SELECT id FROM departments WHERE id=?", (did,)):
        raise ApiError(404, "科室不存在")
    sets, params = [], []
    for f in ("name", "location", "remark", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(did)
        execute("UPDATE departments SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("departments")
    return {"ok": True}

def h_dept_delete(ctx, m, qs, body):
    did = int(m.group(1))
    if q1("SELECT id FROM doctors WHERE dept_id=? LIMIT 1", (did,)):
        raise ApiError(409, "科室下存在医生，禁止删除")
    execute("DELETE FROM departments WHERE id=?", (did,))
    bump_sync("departments")
    return {"ok": True}

# ---------- 医生 ----------

def h_doctor_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("dept_id", [""])[0]:
        cond += " AND d.dept_id=?"; params.append(int(qs["dept_id"][0]))
    if qs.get("title", [""])[0]:
        cond += " AND d.title=?"; params.append(qs["title"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (d.name LIKE ? OR d.specialty LIKE ?)"; params += ["%" + kw + "%"] * 2
    def ex(it):
        dp = q1("SELECT name FROM departments WHERE id=?", (it["dept_id"],))
        it["dept_name"] = dp["name"] if dp else ""
        return it
    return listwrap("SELECT d.* FROM doctors d WHERE " + cond + " ORDER BY d.id", params, qs, ex)

def h_doctor_create(ctx, m, qs, body):
    if not body.get("name") or not body.get("dept_id"):
        raise ApiError(422, "name/dept_id 必填")
    if not q1("SELECT id FROM departments WHERE id=?", (body["dept_id"],)):
        raise ApiError(404, "科室不存在")
    c = execute("INSERT INTO doctors(name,dept_id,title,fee_cents,specialty) VALUES(?,?,?,?,?)",
                (body["name"], body["dept_id"], body.get("title", "住院医师"),
                 K.money_to_cents(body.get("fee", 10)), body.get("specialty")))
    bump_sync("doctors")
    return {"id": c.lastrowid}

def _doctor_or_404(did):
    r = q1("SELECT * FROM doctors WHERE id=?", (did,))
    if not r:
        raise ApiError(404, "医生不存在")
    return r

def h_doctor_get(ctx, m, qs, body):
    d = dict(_doctor_or_404(int(m.group(1))))
    dp = q1("SELECT name FROM departments WHERE id=?", (d["dept_id"],))
    d["dept_name"] = dp["name"] if dp else ""
    return d

def h_doctor_update(ctx, m, qs, body):
    did = int(m.group(1)); _doctor_or_404(did)
    sets, params = [], []
    for f in ("name", "dept_id", "title", "specialty", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if "fee" in body:
        sets.append("fee_cents=?"); params.append(K.money_to_cents(body["fee"]))
    if sets:
        params.append(did)
        execute("UPDATE doctors SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("doctors")
    return {"ok": True}

def h_doctor_delete(ctx, m, qs, body):
    did = int(m.group(1))
    if q1("SELECT id FROM registrations WHERE doctor_id=? LIMIT 1", (did,)):
        raise ApiError(409, "医生有挂号记录，禁止删除（可停诊）")
    execute("DELETE FROM schedules WHERE doctor_id=?", (did,))
    execute("DELETE FROM doctors WHERE id=?", (did,))
    bump_sync("doctors")
    return {"ok": True}

# ---------- 患者 ----------

def h_patient_list(ctx, m, qs, body):
    cond, params = "1=1", []
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (name LIKE ? OR mrn LIKE ? OR phone LIKE ?)"; params += ["%" + kw + "%"] * 3
    if qs.get("gender", [""])[0]:
        cond += " AND gender=?"; params.append(qs["gender"][0])
    if qs.get("insurance_type", [""])[0]:
        cond += " AND insurance_type=?"; params.append(qs["insurance_type"][0])
    return listwrap("SELECT * FROM patients WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_patient_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    mrn = body.get("mrn") or "P%04d" % next_seq("mrn")
    if q1("SELECT id FROM patients WHERE mrn=?", (mrn,)):
        raise ApiError(409, "档案号已存在")
    itype = body.get("insurance_type", "self")
    if itype not in K.INSURANCE_RATES:
        raise ApiError(422, "insurance_type 须为 employee/resident/self")
    c = execute("INSERT INTO patients(mrn,name,gender,birth,phone,allergy,insurance_type,insurance_no) VALUES(?,?,?,?,?,?,?,?)",
                (mrn, body["name"], body.get("gender", "M"), body.get("birth"), body.get("phone"),
                 body.get("allergy"), itype, body.get("insurance_no")))
    bump_sync("patients")
    return {"id": c.lastrowid, "mrn": mrn}

def _patient_or_404(pid):
    r = q1("SELECT * FROM patients WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "患者不存在")
    return r

def h_patient_get(ctx, m, qs, body):
    return dict(_patient_or_404(int(m.group(1))))

def h_patient_update(ctx, m, qs, body):
    pid = int(m.group(1)); _patient_or_404(pid)
    sets, params = [], []
    for f in ("name", "gender", "birth", "phone", "allergy", "insurance_type", "insurance_no"):
        if f in body:
            if f == "insurance_type" and body[f] not in K.INSURANCE_RATES:
                raise ApiError(422, "insurance_type 非法")
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(pid)
        execute("UPDATE patients SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("patients")
    return {"ok": True}

def h_patient_delete(ctx, m, qs, body):
    pid = int(m.group(1))
    if q1("SELECT id FROM registrations WHERE patient_id=? LIMIT 1", (pid,)):
        raise ApiError(409, "患者有就诊记录，禁止删除")
    execute("DELETE FROM patients WHERE id=?", (pid,))
    bump_sync("patients")
    return {"ok": True}

def h_patient_visits(ctx, m, qs, body):
    pid = int(m.group(1)); _patient_or_404(pid)
    regs = [dict(r) for r in q("SELECT * FROM registrations WHERE patient_id=? ORDER BY id DESC", (pid,))]
    for r in regs:
        cr = q1("SELECT * FROM clinic_records WHERE registration_id=?", (r["id"],))
        r["record"] = dict(cr) if cr else None
        rxs = [dict(x) for x in q("SELECT * FROM prescriptions WHERE registration_id=?", (r["id"],))]
        r["prescriptions"] = rxs
    return {"items": regs, "total": len(regs)}

# ---------- 药品 ----------

def h_drug_list(ctx, m, qs, body):
    cond, params = "1=1", []
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (name LIKE ? OR spec LIKE ?)"; params += ["%" + kw + "%"] * 2
    if qs.get("rx_required", [""])[0] != "":
        cond += " AND rx_required=?"; params.append(int(qs["rx_required"][0]))
    def ex(it):
        rows = q("SELECT SUM(qty) s FROM inventory WHERE drug_id=?", (it["id"],))
        it["stock"] = int(rows[0]["s"] or 0)
        return it
    return listwrap("SELECT * FROM drugs WHERE " + cond + " ORDER BY id", params, qs, ex)

def h_drug_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    c = execute("INSERT INTO drugs(name,spec,unit,price_cents,max_dose,rx_required,safe_stock) VALUES(?,?,?,?,?,?,?)",
                (body["name"], body.get("spec"), body.get("unit", "盒"),
                 K.money_to_cents(body.get("price", 0)), float(body.get("max_dose", 0) or 0),
                 1 if body.get("rx_required", 1) else 0, int(body.get("safe_stock", 10) or 10)))
    bump_sync("drugs")
    return {"id": c.lastrowid}

def _drug_or_404(did):
    r = q1("SELECT * FROM drugs WHERE id=?", (did,))
    if not r:
        raise ApiError(404, "药品不存在")
    return r

def h_drug_get(ctx, m, qs, body):
    d = dict(_drug_or_404(int(m.group(1))))
    d["batches"] = [dict(r) for r in q("SELECT * FROM inventory WHERE drug_id=? ORDER BY expire_at", (d["id"],))]
    return d

def h_drug_update(ctx, m, qs, body):
    did = int(m.group(1)); _drug_or_404(did)
    sets, params = [], []
    for f in ("name", "spec", "unit", "max_dose", "rx_required", "safe_stock", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if "price" in body:
        sets.append("price_cents=?"); params.append(K.money_to_cents(body["price"]))
    if sets:
        params.append(did)
        execute("UPDATE drugs SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("drugs")
    return {"ok": True}

def h_drug_delete(ctx, m, qs, body):
    did = int(m.group(1))
    if q1("SELECT id FROM prescription_items WHERE drug_id=? LIMIT 1", (did,)):
        raise ApiError(409, "药品已有处方记录，禁止删除")
    execute("DELETE FROM inventory WHERE drug_id=?", (did,))
    execute("DELETE FROM drugs WHERE id=?", (did,))
    bump_sync("drugs")
    return {"ok": True}

# ---------- 供应商 ----------

def h_supplier_list(ctx, m, qs, body):
    kw = qs.get("keyword", [""])[0]
    cond, params = "1=1", []
    if kw:
        cond = "(name LIKE ? OR contact LIKE ?)"; params = ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM suppliers WHERE " + cond + " ORDER BY id", params, qs)

def h_supplier_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    c = execute("INSERT INTO suppliers(name,contact,phone,credit_days) VALUES(?,?,?,?)",
                (body["name"], body.get("contact"), body.get("phone"), int(body.get("credit_days", 30) or 30)))
    return {"id": c.lastrowid}

def h_supplier_update(ctx, m, qs, body):
    sid = int(m.group(1))
    if not q1("SELECT id FROM suppliers WHERE id=?", (sid,)):
        raise ApiError(404, "供应商不存在")
    sets, params = [], []
    for f in ("name", "contact", "phone", "credit_days"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(sid)
        execute("UPDATE suppliers SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_supplier_delete(ctx, m, qs, body):
    sid = int(m.group(1))
    if q1("SELECT id FROM purchases WHERE supplier_id=? LIMIT 1", (sid,)):
        raise ApiError(409, "供应商有采购记录，禁止删除")
    execute("DELETE FROM suppliers WHERE id=?", (sid,))
    return {"ok": True}

# ---------- 排班 ----------

def h_sched_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("doctor_id", [""])[0]:
        cond += " AND doctor_id=?"; params.append(int(qs["doctor_id"][0]))
    if qs.get("date", [""])[0]:
        cond += " AND sched_date=?"; params.append(qs["date"][0])
    if qs.get("date_from", [""])[0]:
        cond += " AND sched_date>=?"; params.append(qs["date_from"][0])
    if qs.get("date_to", [""])[0]:
        cond += " AND sched_date<=?"; params.append(qs["date_to"][0])
    if qs.get("period", [""])[0]:
        cond += " AND period=?"; params.append(qs["period"][0])
    def ex(it):
        d = q1("SELECT name,title FROM doctors WHERE id=?", (it["doctor_id"],))
        it["doctor_name"] = d["name"] if d else ""
        it["doctor_title"] = d["title"] if d else ""
        return it
    return listwrap("SELECT * FROM schedules WHERE " + cond + " ORDER BY sched_date, period, doctor_id", params, qs, ex)

def h_sched_create(ctx, m, qs, body):
    for f in ("doctor_id", "sched_date", "period"):
        if not body.get(f):
            raise ApiError(422, f + " 必填")
    _doctor_or_404(body["doctor_id"])
    if body["period"] not in K.PERIODS:
        raise ApiError(422, "period 须为 AM/PM")
    rows = q("SELECT id,doctor_id,sched_date,period FROM schedules WHERE sched_date=?", (body["sched_date"],))
    if K.sched_conflict(rows, body["doctor_id"], body["sched_date"], body["period"]):
        raise ApiError(422, "该医生在该时段已有排班")
    c = execute("INSERT INTO schedules(doctor_id,sched_date,period,quota) VALUES(?,?,?,?)",
                (body["doctor_id"], body["sched_date"], body["period"], int(body.get("quota", 20) or 20)))
    bump_sync("schedules")
    return {"id": c.lastrowid}

def _sched_or_404(sid):
    r = q1("SELECT * FROM schedules WHERE id=?", (sid,))
    if not r:
        raise ApiError(404, "排班不存在")
    return r

def h_sched_update(ctx, m, qs, body):
    sid = int(m.group(1)); s = _sched_or_404(sid)
    doctor_id = body.get("doctor_id", s["doctor_id"])
    sched_date = body.get("sched_date", s["sched_date"])
    period = body.get("period", s["period"])
    if period not in K.PERIODS:
        raise ApiError(422, "period 须为 AM/PM")
    rows = q("SELECT id,doctor_id,sched_date,period FROM schedules WHERE sched_date=?", (sched_date,))
    if K.sched_conflict(rows, doctor_id, sched_date, period, exclude_id=sid):
        raise ApiError(422, "该医生在该时段已有排班")
    quota = int(body.get("quota", s["quota"]) or s["quota"])
    if quota < s["booked"]:
        raise ApiError(422, "号源不能小于已挂号数")
    execute("UPDATE schedules SET doctor_id=?,sched_date=?,period=?,quota=? WHERE id=?",
            (doctor_id, sched_date, period, quota, sid))
    bump_sync("schedules")
    return {"ok": True}

def h_sched_delete(ctx, m, qs, body):
    sid = int(m.group(1)); s = _sched_or_404(sid)
    if q1("SELECT id FROM registrations WHERE schedule_id=? AND status NOT IN ('cancelled') LIMIT 1", (sid,)):
        raise ApiError(409, "排班已有挂号，禁止删除")
    execute("DELETE FROM schedules WHERE id=?", (sid,))
    bump_sync("schedules")
    return {"ok": True}

# ---------- 挂号 ----------

REG_ACTIONS = {"to_called": "called", "to_in_consult": "in_consult", "to_done": "done", "to_cancelled": "cancelled"}

def _reg_full(rid):
    r = q1("SELECT * FROM registrations WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "挂号单不存在")
    d = dict(r)
    p = q1("SELECT name,phone,mrn FROM patients WHERE id=?", (r["patient_id"],))
    d["patient"] = dict(p) if p else None
    dc = q1("SELECT name,title FROM doctors WHERE id=?", (r["doctor_id"] or 0,))
    d["doctor_name"] = dc["name"] if dc else None
    dp = q1("SELECT name FROM departments WHERE id=?", (r["dept_id"] or 0,))
    d["dept_name"] = dp["name"] if dp else None
    return d

def h_reg_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("patient_id", "doctor_id", "status"):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(int(qs[f][0]) if f.endswith("_id") else qs[f][0])
    if qs.get("date", [""])[0]:
        cond += " AND date(created_at)=?"; params.append(qs["date"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND no LIKE ?"; params.append("%" + kw + "%")
    return listwrap("SELECT * FROM registrations WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_reg_get(ctx, m, qs, body):
    return _reg_full(int(m.group(1)))

def h_reg_create(ctx, m, qs, body):
    for f in ("patient_id", "schedule_id"):
        if not body.get(f):
            raise ApiError(422, f + " 必填")
    p = _patient_or_404(body["patient_id"])
    s = _sched_or_404(body["schedule_id"])
    if s["status"] != "open":
        raise ApiError(422, "排班已关闭")
    if not K.sched_quota_ok(s["quota"], s["booked"]):
        raise ApiError(422, "排班余号不足")
    no = make_no("GH", "registration_no")
    c = execute("INSERT INTO registrations(no,patient_id,schedule_id,doctor_id,dept_id,fee_cents,status,no_in_queue) VALUES(?,?,?,?,?,?,?,?)",
                (no, body["patient_id"], body["schedule_id"], s["doctor_id"], _doctor_or_404(s["doctor_id"])["dept_id"],
                 s and q1("SELECT fee_cents FROM doctors WHERE id=?", (s["doctor_id"],))["fee_cents"],
                 "waiting", s["booked"] + 1))
    execute("UPDATE schedules SET booked=booked+1 WHERE id=?", (s["id"],))
    bump_sync("registrations")
    return {"id": c.lastrowid, "no": no, "patient_name": p["name"], "fee_cents": q1("SELECT fee_cents FROM registrations WHERE id=?", (c.lastrowid,))["fee_cents"]}

def h_reg_transition(ctx, m, qs, body):
    rid = int(m.group(1))
    r = q1("SELECT * FROM registrations WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "挂号单不存在")
    action = body.get("action") or ""
    if action not in REG_ACTIONS:
        raise ApiError(422, "action 须为 " + "/".join(REG_ACTIONS))
    nxt = REG_ACTIONS[action]
    if not K.can_transition(K.REG_TRANS, r["status"], nxt):
        raise ApiError(422, "挂号 %s 不允许 %s → %s" % (r["no"], r["status"], nxt),
                       )
    if nxt == "cancelled":
        execute("UPDATE schedules SET booked=booked-1 WHERE id=? AND booked>0", (r["schedule_id"],))
    execute("UPDATE registrations SET status=? WHERE id=?", (nxt, rid))
    if nxt == "done":
        cr = q1("SELECT id FROM clinic_records WHERE registration_id=?", (rid,))
        if not cr:
            execute("INSERT INTO clinic_records(registration_id,patient_id,doctor_id,chief_complaint,history,diagnosis,advice) VALUES(?,?,?,'','','','')",
                    (rid, r["patient_id"], r["doctor_id"]))
    bump_sync("registrations")
    return {"ok": True, "status": nxt}

def h_reg_queue(ctx, m, qs, body):
    sid = qs.get("schedule_id", [""])[0]
    cond = "status IN ('waiting','called')"
    params = []
    if sid:
        cond += " AND schedule_id=?"; params.append(int(sid))
    rows = q("SELECT * FROM registrations WHERE " + cond + " ORDER BY no_in_queue", params)
    items = []
    for r in rows:
        d = dict(r)
        p = q1("SELECT name FROM patients WHERE id=?", (r["patient_id"],))
        d["patient_name"] = p["name"] if p else ""
        dc = q1("SELECT name FROM doctors WHERE id=?", (r["doctor_id"] or 0,))
        d["doctor_name"] = dc["name"] if dc else ""
        items.append(d)
    return {"items": items, "total": len(items), "waiting": sum(1 for i in items if i["status"] == "waiting")}

# ---------- 病历 ----------

def h_record_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("patient_id", [""])[0]:
        cond += " AND patient_id=?"; params.append(int(qs["patient_id"][0]))
    if qs.get("doctor_id", [""])[0]:
        cond += " AND doctor_id=?"; params.append(int(qs["doctor_id"][0]))
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (chief_complaint LIKE ? OR diagnosis LIKE ?)"; params += ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM clinic_records WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_record_create(ctx, m, qs, body):
    rid = body.get("registration_id")
    if not rid:
        raise ApiError(422, "registration_id 必填")
    reg = q1("SELECT * FROM registrations WHERE id=?", (rid,))
    if not reg:
        raise ApiError(404, "挂号单不存在")
    if q1("SELECT id FROM clinic_records WHERE registration_id=?", (rid,)):
        raise ApiError(409, "该挂号单已有病历")
    c = execute("INSERT INTO clinic_records(registration_id,patient_id,doctor_id,chief_complaint,history,diagnosis,advice) VALUES(?,?,?,?,?,?,?)",
                (rid, reg["patient_id"], reg["doctor_id"], body.get("chief_complaint", ""),
                 body.get("history", ""), body.get("diagnosis", ""), body.get("advice", "")))
    bump_sync("clinic_records")
    return {"id": c.lastrowid}

def h_record_get(ctx, m, qs, body):
    r = q1("SELECT * FROM clinic_records WHERE id=?", (int(m.group(1)),))
    if not r:
        raise ApiError(404, "病历不存在")
    return dict(r)

def h_record_update(ctx, m, qs, body):
    rid = int(m.group(1))
    if not q1("SELECT id FROM clinic_records WHERE id=?", (rid,)):
        raise ApiError(404, "病历不存在")
    sets, params = [], []
    for f in ("chief_complaint", "history", "diagnosis", "advice"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        sets.append("version=version+1"); params.append(rid)
        execute("UPDATE clinic_records SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("clinic_records")
    return {"ok": True}

# ---------- 处方 ----------

RX_ACTIONS = {"to_submitted": "submitted", "to_dispensed": "dispensed", "to_cancelled": "cancelled"}

def _rx_full(rid):
    r = q1("SELECT * FROM prescriptions WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "处方不存在")
    d = dict(r)
    d["items"] = [dict(x) for x in q("SELECT * FROM prescription_items WHERE prescription_id=? ORDER BY id", (rid,))]
    p = q1("SELECT name,mrn FROM patients WHERE id=?", (r["patient_id"],))
    d["patient"] = dict(p) if p else None
    dc = q1("SELECT name,title FROM doctors WHERE id=?", (r["doctor_id"] or 0,))
    d["doctor_name"] = dc["name"] if dc else None
    return d

def h_rx_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("patient_id", "doctor_id", "status"):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(int(qs[f][0]) if f.endswith("_id") else qs[f][0])
    if qs.get("date_from", [""])[0]:
        cond += " AND date(created_at)>=?"; params.append(qs["date_from"][0])
    if qs.get("date_to", [""])[0]:
        cond += " AND date(created_at)<=?"; params.append(qs["date_to"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND no LIKE ?"; params.append("%" + kw + "%")
    return listwrap("SELECT * FROM prescriptions WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_rx_get(ctx, m, qs, body):
    return _rx_full(int(m.group(1)))

def h_rx_create(ctx, m, qs, body):
    if not body.get("patient_id") or not body.get("doctor_id"):
        raise ApiError(422, "patient_id/doctor_id 必填")
    _patient_or_404(body["patient_id"]); _doctor_or_404(body["doctor_id"])
    items = body.get("items") or []
    if not items:
        raise ApiError(422, "items 不能为空")
    totals, over_dose = [], []
    prepared = []
    for it in items:
        if not it.get("drug_id"):
            raise ApiError(422, "items[].drug_id 必填")
        drug = _drug_or_404(it["drug_id"])
        qty = int(it.get("qty", 1) or 1)
        dose = float(it.get("dose", 0) or 0)
        amt = K.calc_rx_amount_cents(qty, drug["price_cents"])
        totals.append(amt)
        if K.dose_over(dose, drug["max_dose"]):
            over_dose.append(drug["name"])
        prepared.append((drug, it, qty, dose, amt))
    total = K.rx_total_cents(totals)
    no = make_no("CF", "prescription_no")
    c = execute("INSERT INTO prescriptions(no,patient_id,doctor_id,registration_id,status,total_cents) VALUES(?,?,?,?,?,?)",
                (no, body["patient_id"], body["doctor_id"], body.get("registration_id"), "draft", total))
    rx_id = c.lastrowid
    for drug, it, qty, dose, amt in prepared:
        execute("INSERT INTO prescription_items(prescription_id,drug_id,drug_name,dose,frequency,days,qty,price_cents,amount_cents) VALUES(?,?,?,?,?,?,?,?,?)",
                (rx_id, drug["id"], drug["name"], dose, it.get("frequency", ""), int(it.get("days", 1) or 1), qty, drug["price_cents"], amt))
    for name in over_dose:
        execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('dose_over',?,?,?,35,'warn')",
                (rx_id, "处方剂量超限", "处方 %s 中「%s」单次剂量超过上限" % (no, name)))
    bump_sync("prescriptions")
    d = _rx_full(rx_id)
    d["dose_warnings"] = over_dose
    return d

def _dispense_rx(rx):
    """FEFO 扣库存 + 发药记录。库存不足抛 422（调用方保证在事务检查后执行）。"""
    items = q("SELECT * FROM prescription_items WHERE prescription_id=?", (rx["id"],))
    logs = []
    for it in items:
        rows = q("SELECT * FROM inventory WHERE drug_id=?", (it["drug_id"],))
        allocs, shortfall = K.fefe_batches(rows, it["qty"])
        if shortfall > 0:
            raise ApiError(422, "库存不足: %s（需 %d，缺 %d）" % (it["drug_name"], it["qty"], shortfall))
        for inv_id, batch_no, take in allocs:
            execute("UPDATE inventory SET qty=qty-?, version=version+1 WHERE id=?", (take, inv_id))
            execute("INSERT INTO pharmacy_logs(prescription_id,drug_id,drug_name,qty,batch_no,operator) VALUES(?,?,?,?,?,?)",
                    (rx["id"], it["drug_id"], it["drug_name"], take, batch_no, "system"))
            logs.append({"drug": it["drug_name"], "batch_no": batch_no, "qty": take})
        bump_sync("inventory")
    return logs

def h_rx_transition(ctx, m, qs, body):
    rxid = int(m.group(1))
    r = q1("SELECT * FROM prescriptions WHERE id=?", (rxid,))
    if not r:
        raise ApiError(404, "处方不存在")
    action = body.get("action") or ""
    if action not in RX_ACTIONS:
        raise ApiError(422, "action 须为 " + "/".join(RX_ACTIONS))
    nxt = RX_ACTIONS[action]
    if not K.can_transition(K.RX_TRANS, r["status"], nxt):
        raise ApiError(422, "处方 %s 不允许 %s → %s" % (r["no"], r["status"], nxt))
    logs = []
    if nxt == "dispensed":
        logs = _dispense_rx(r)
    execute("UPDATE prescriptions SET status=? WHERE id=?", (nxt, rxid))
    bump_sync("prescriptions")
    return {"ok": True, "status": nxt, "dispensed": logs}

# ---------- 收费 ----------

def h_charge_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("patient_id", "pay_method", "status"):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(int(qs[f][0]) if f == "patient_id" else qs[f][0])
    if qs.get("date_from", [""])[0]:
        cond += " AND date(created_at)>=?"; params.append(qs["date_from"][0])
    if qs.get("date_to", [""])[0]:
        cond += " AND date(created_at)<=?"; params.append(qs["date_to"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND no LIKE ?"; params.append("%" + kw + "%")
    return listwrap("SELECT * FROM charges WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_charge_get(ctx, m, qs, body):
    r = q1("SELECT * FROM charges WHERE id=?", (int(m.group(1)),))
    if not r:
        raise ApiError(404, "收费单不存在")
    d = dict(r)
    d["items"] = [dict(x) for x in q("SELECT * FROM charge_items WHERE charge_id=? ORDER BY id", (r["id"],))]
    p = q1("SELECT name,mrn,insurance_type FROM patients WHERE id=?", (r["patient_id"] or 0,))
    d["patient"] = dict(p) if p else None
    return d

def h_charge_create(ctx, m, qs, body):
    reg_id = body.get("registration_id")
    rx_ids = body.get("prescription_ids") or []
    if not reg_id and not rx_ids:
        raise ApiError(422, "registration_id / prescription_ids 至少一项")
    patient_id = body.get("patient_id")
    pay_method = body.get("pay_method", "cash")
    if pay_method not in ("cash", "wechat", "alipay", "insurance"):
        raise ApiError(422, "pay_method 非法")
    total = 0
    details = []
    if reg_id:
        reg = q1("SELECT * FROM registrations WHERE id=?", (reg_id,))
        if not reg:
            raise ApiError(404, "挂号单不存在")
        if reg["paid"]:
            raise ApiError(409, "该挂号已收费")
        patient_id = patient_id or reg["patient_id"]
        total += reg["fee_cents"]
        details.append(("registration", "挂号费", reg["fee_cents"]))
    for rxid in rx_ids:
        rx = q1("SELECT * FROM prescriptions WHERE id=?", (rxid,))
        if not rx:
            raise ApiError(404, "处方 %d 不存在" % rxid)
        if rx["status"] not in ("draft", "submitted", "dispensed"):
            raise ApiError(422, "处方 %s 状态为 %s，不可收费" % (rx["no"], rx["status"]))
        dup = q1("SELECT id FROM charges WHERE status='paid' AND (',' || prescription_ids || ',') LIKE ? LIMIT 1",
                 ("%%,%d,%%" % rxid,))
        if dup:
            raise ApiError(409, "处方 %s 已收费，不可重复收费" % rx["no"])
        patient_id = patient_id or rx["patient_id"]
        total += rx["total_cents"]
        details.append(("prescription", "处方费 " + rx["no"], rx["total_cents"]))
    p = _patient_or_404(patient_id)
    rate = K.insurance_rate(p["insurance_type"])
    paid = K.payable_cents(total, rate)
    no = make_no("SF", "charge_no")
    c = execute("INSERT INTO charges(no,patient_id,registration_id,prescription_ids,total_cents,discount_rate,paid_cents,pay_method,status) VALUES(?,?,?,?,?,?,?,?,?)",
                (no, patient_id, reg_id, ",".join(str(x) for x in rx_ids), total, rate, paid, pay_method, "paid"))
    cid = c.lastrowid
    for itype, name, amt in details:
        execute("INSERT INTO charge_items(charge_id,item_type,item_name,amount_cents) VALUES(?,?,?,?)", (cid, itype, name, amt))
    if reg_id:
        execute("UPDATE registrations SET paid=1 WHERE id=?", (reg_id,))
    execute("INSERT INTO transactions(ttype,amount_cents,ref_type,ref_id,pay_method,note) VALUES('income',?,?,?,?,?)",
            (paid, "charge", cid, pay_method, "收费 " + no))
    bump_sync("charges")
    bump_sync("transactions")
    return {"id": cid, "no": no, "total_cents": total, "discount_rate": rate, "paid_cents": paid,
            "patient_name": p["name"], "insurance_type": p["insurance_type"]}

def h_charge_refund(ctx, m, qs, body):
    cid = int(m.group(1))
    r = q1("SELECT * FROM charges WHERE id=?", (cid,))
    if not r:
        raise ApiError(404, "收费单不存在")
    if r["status"] != "paid":
        raise ApiError(422, "仅已支付收费单可退费")
    execute("UPDATE charges SET status='refunded' WHERE id=?", (cid,))
    if r["registration_id"]:
        execute("UPDATE registrations SET paid=0 WHERE id=? AND status IN ('waiting','called')", (r["registration_id"],))
    execute("INSERT INTO transactions(ttype,amount_cents,ref_type,ref_id,note) VALUES('refund',?, 'charge', ?, '退费 ' || ?)",
            (-r["paid_cents"], cid, r["no"]))
    bump_sync("transactions")
    return {"ok": True, "refund_cents": r["paid_cents"]}

# ---------- 药房 ----------

def h_pharmacy_pending(ctx, m, qs, body):
    rows = q("SELECT * FROM prescriptions WHERE status='submitted' ORDER BY id")
    items = [_rx_full(r["id"]) for r in rows]
    return {"items": items, "total": len(items)}

def h_pharmacy_logs(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("drug_id", [""])[0]:
        cond += " AND drug_id=?"; params.append(int(qs["drug_id"][0]))
    if qs.get("date", [""])[0]:
        cond += " AND date(created_at)=?"; params.append(qs["date"][0])
    return listwrap("SELECT * FROM pharmacy_logs WHERE " + cond + " ORDER BY id DESC", params, qs)

# ---------- 库存 ----------

def h_inv_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("drug_id", [""])[0]:
        cond += " AND i.drug_id=?"; params.append(int(qs["drug_id"][0]))
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND d.name LIKE ?"; params.append("%" + kw + "%")
    if qs.get("near_expiry_days", [""])[0]:
        days = int(qs["near_expiry_days"][0])
        from datetime import date as _d, timedelta as _td
        limit = (_d.today() + _td(days=days)).isoformat()
        cond += " AND i.expire_at<=?"; params.append(limit)
    def ex(it):
        it["drug_name"] = it.pop("name", None) if "name" in it.keys() else it.get("drug_name")
        return it
    return listwrap("SELECT i.*, d.name AS drug_name, d.spec, d.safe_stock FROM inventory i JOIN drugs d ON d.id=i.drug_id WHERE " + cond + " ORDER BY i.expire_at, i.id", params, qs)

def h_inv_summary(ctx, m, qs, body):
    did = qs.get("drug_id", [""])[0]
    if not did:
        raise ApiError(422, "drug_id 必填")
    rows = q("SELECT batch_no,qty,expire_at FROM inventory WHERE drug_id=? ORDER BY expire_at", (did,))
    return {"drug_id": int(did), "total": sum(int(r["qty"] or 0) for r in rows), "batches": [dict(r) for r in rows]}

# ---------- 采购 ----------

PURCHASE_ACTIONS = {"to_submitted": "submitted", "to_received": "received", "to_cancelled": "cancelled"}

def _purchase_full(pid):
    r = q1("SELECT * FROM purchases WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "采购单不存在")
    d = dict(r)
    d["items"] = [dict(x) for x in q("SELECT pi.*, dg.name AS drug_name FROM purchase_items pi JOIN drugs dg ON dg.id=pi.drug_id WHERE pi.purchase_id=? ORDER BY pi.id", (pid,))]
    s = q1("SELECT name,phone FROM suppliers WHERE id=?", (r["supplier_id"],))
    d["supplier"] = dict(s) if s else None
    return d

def h_purchase_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    if qs.get("supplier_id", [""])[0]:
        cond += " AND supplier_id=?"; params.append(int(qs["supplier_id"][0]))
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND no LIKE ?"; params.append("%" + kw + "%")
    return listwrap("SELECT * FROM purchases WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_purchase_get(ctx, m, qs, body):
    return _purchase_full(int(m.group(1)))

def h_purchase_create(ctx, m, qs, body):
    if not body.get("supplier_id"):
        raise ApiError(422, "supplier_id 必填")
    if not q1("SELECT id FROM suppliers WHERE id=?", (body["supplier_id"],)):
        raise ApiError(404, "供应商不存在")
    items = body.get("items") or []
    if not items:
        raise ApiError(422, "items 不能为空")
    no = make_no("CG", "purchase_no")
    total = K.purchase_total_cents(items)
    c = execute("INSERT INTO purchases(no,supplier_id,status,total_cents) VALUES(?,?,?,?)",
                (no, body["supplier_id"], "draft", total))
    pid = c.lastrowid
    for it in items:
        if not it.get("drug_id"):
            raise ApiError(422, "items[].drug_id 必填")
        _drug_or_404(it["drug_id"])
        qty = int(it.get("qty", 0) or 0)
        cost = int(it.get("cost_cents", 0) or 0)
        execute("INSERT INTO purchase_items(purchase_id,drug_id,qty,cost_cents,amount_cents,batch_no,expiry) VALUES(?,?,?,?,?,?,?)",
                (pid, it["drug_id"], qty, cost, qty * cost, it.get("batch_no"), it.get("expiry")))
    return _purchase_full(pid)

def h_purchase_item_add(ctx, m, qs, body):
    pid = int(m.group(1))
    r = q1("SELECT * FROM purchases WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "采购单不存在")
    if r["status"] != "draft":
        raise ApiError(422, "仅草稿采购单可加明细")
    if not body.get("drug_id"):
        raise ApiError(422, "drug_id 必填")
    _drug_or_404(body["drug_id"])
    qty = int(body.get("qty", 0) or 0)
    cost = int(body.get("cost_cents", 0) or 0)
    execute("INSERT INTO purchase_items(purchase_id,drug_id,qty,cost_cents,amount_cents,batch_no,expiry) VALUES(?,?,?,?,?,?,?)",
            (pid, body["drug_id"], qty, cost, qty * cost, body.get("batch_no"), body.get("expiry")))
    total = q1("SELECT SUM(amount_cents) s FROM purchase_items WHERE purchase_id=?", (pid,))["s"] or 0
    execute("UPDATE purchases SET total_cents=? WHERE id=?", (total, pid))
    return _purchase_full(pid)

def h_purchase_transition(ctx, m, qs, body):
    pid = int(m.group(1))
    r = q1("SELECT * FROM purchases WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "采购单不存在")
    action = body.get("action") or ""
    if action not in PURCHASE_ACTIONS:
        raise ApiError(422, "action 须为 " + "/".join(PURCHASE_ACTIONS))
    nxt = PURCHASE_ACTIONS[action]
    if not K.can_transition(K.PURCHASE_TRANS, r["status"], nxt):
        raise ApiError(422, "采购单 %s 不允许 %s → %s" % (r["no"], r["status"], nxt))
    if nxt == "received":
        items = q("SELECT * FROM purchase_items WHERE purchase_id=?", (pid,))
        if not items:
            raise ApiError(422, "采购单无明细，不可入库")
        for it in items:
            batch = it["batch_no"] or ("%s-B%d" % (r["no"], it["id"]))
            exist = q1("SELECT id,qty FROM inventory WHERE drug_id=? AND batch_no=?", (it["drug_id"], batch))
            if exist:
                execute("UPDATE inventory SET qty=qty+?, expire_at=COALESCE(?, expire_at), version=version+1 WHERE id=?",
                        (it["qty"], it["expiry"], exist["id"]))
            else:
                execute("INSERT INTO inventory(drug_id,batch_no,qty,expire_at) VALUES(?,?,?,?)",
                        (it["drug_id"], batch, it["qty"], it["expiry"]))
        sup = q1("SELECT * FROM suppliers WHERE id=?", (r["supplier_id"],))
        execute("UPDATE suppliers SET payable_cents=payable_cents+? WHERE id=?", (r["total_cents"], r["supplier_id"]))
        execute("INSERT INTO transactions(ttype,amount_cents,ref_type,ref_id,note) VALUES('expense',?, 'purchase', ?, '采购入库 ' || ?)",
                (-r["total_cents"], pid, r["no"]))
        bump_sync("inventory")
        bump_sync("transactions")
    execute("UPDATE purchases SET status=? WHERE id=?", (nxt, pid))
    bump_sync("purchases")
    return {"ok": True, "status": nxt}

def h_purchase_delete(ctx, m, qs, body):
    pid = int(m.group(1))
    r = q1("SELECT * FROM purchases WHERE id=?", (pid,))
    if not r:
        raise ApiError(404, "采购单不存在")
    if r["status"] not in ("draft", "cancelled"):
        raise ApiError(422, "仅草稿/已取消采购单可删除")
    execute("DELETE FROM purchase_items WHERE purchase_id=?", (pid,))
    execute("DELETE FROM purchases WHERE id=?", (pid,))
    return {"ok": True}

# ---------- 财务 ----------

def h_tx_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("ttype", [""])[0]:
        cond += " AND ttype=?"; params.append(qs["ttype"][0])
    if qs.get("date_from", [""])[0]:
        cond += " AND date(created_at)>=?"; params.append(qs["date_from"][0])
    if qs.get("date_to", [""])[0]:
        cond += " AND date(created_at)<=?"; params.append(qs["date_to"][0])
    return listwrap("SELECT * FROM transactions WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_finance_summary(ctx, m, qs, body):
    d = qs.get("date", [""])[0] or time.strftime("%Y-%m-%d")
    income = q1("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions WHERE ttype='income' AND date(created_at)=?", (d,))["s"]
    refund = q1("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions WHERE ttype='refund' AND date(created_at)=?", (d,))["s"]
    expense = q1("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions WHERE ttype='expense' AND date(created_at)=?", (d,))["s"]
    by_method = {}
    for r in q("SELECT pay_method m, SUM(amount_cents) s FROM transactions WHERE ttype='income' AND date(created_at)=? GROUP BY pay_method", (d,)):
        by_method[r["m"] or "cash"] = int(r["s"] or 0)
    charge_count = q1("SELECT COUNT(*) c FROM charges WHERE date(created_at)=?", (d,))["c"]
    rx_count = q1("SELECT COUNT(*) c FROM prescriptions WHERE date(created_at)=?", (d,))["c"]
    return {"date": d, "income_cents": int(income), "refund_cents": int(refund), "expense_cents": int(expense),
            "by_method": by_method, "charge_count": charge_count, "rx_count": rx_count}

# ---------- 风险 ----------

def h_risk_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("status", "grade", "rtype"):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(qs[f][0])
    return listwrap("SELECT * FROM risks WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_risk_scan(ctx, m, qs, body):
    created = 0
    by_type = {}
    today = datetime.date.today()
    def _exists(rtype, ref_id):
        return q1("SELECT id FROM risks WHERE rtype=? AND ref_id=? AND status='open'", (rtype, ref_id))
    # 1 药品低库存（按批次合计）
    for r in q("SELECT d.id, d.name, d.safe_stock, COALESCE(SUM(i.qty),0) s FROM drugs d LEFT JOIN inventory i ON i.drug_id=d.id GROUP BY d.id"):
        if K.low_stock_check(int(r["s"]), r["safe_stock"]):
            if not _exists("drug_low_stock", r["id"]):
                execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('drug_low_stock',?,?,?,30,'warn')",
                        (r["id"], "药品低库存", "%s 当前库存 %d ≤ 安全库存 %d" % (r["name"], r["s"], r["safe_stock"])))
                created += 1; by_type["drug_low_stock"] = by_type.get("drug_low_stock", 0) + 1
    # 2 效期临期
    for r in q("SELECT i.id, d.name, i.batch_no, i.expire_at FROM inventory i JOIN drugs d ON d.id=i.drug_id WHERE i.qty>0"):
        chk = K.expiry_check(r["expire_at"], 90, today)
        if chk and not _exists("drug_expiry", r["id"]):
            execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('drug_expiry',?,?,?,25,'warn')",
                    (r["id"], "药品效期预警", "%s 批次 %s 效期 %s，剩余不足 90 天" % (r["name"], r["batch_no"], r["expire_at"])))
            created += 1; by_type["drug_expiry"] = by_type.get("drug_expiry", 0) + 1
    # 3 挂号超时未就诊
    for r in q("SELECT id,no,created_at FROM registrations WHERE status IN ('waiting','called')"):
        chk = K.overdue_registration_check(r["created_at"], 24)
        if chk and not _exists("patient_overdue", r["id"]):
            execute("INSERT INTO risks(rtype,ref_id,title,detail,score,grade) VALUES('patient_overdue',?,?,?,20,'warn')",
                    (r["id"], "挂号超时未就诊", "挂号 %s 超过 24 小时未就诊未退号" % r["no"]))
            created += 1; by_type["patient_overdue"] = by_type.get("patient_overdue", 0) + 1
    return {"created": created, "by_type": by_type}

def h_risk_resolve(ctx, m, qs, body):
    rid = int(m.group(1))
    r = q1("SELECT * FROM risks WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "风险不存在")
    if r["status"] != "open":
        raise ApiError(422, "风险已处理")
    execute("UPDATE risks SET status='resolved', resolved_by=?, note=? WHERE id=?",
            (ctx["user"].get("name") or "", body.get("note"), rid))
    return {"ok": True}

# ---------- 仪表盘 ----------

def h_dashboard(ctx, m, qs, body):
    d = qs.get("date", [""])[0] or time.strftime("%Y-%m-%d")
    regs_today = q1("SELECT COUNT(*) c FROM registrations WHERE date(created_at)=?", (d,))["c"]
    done_today = q1("SELECT COUNT(*) c FROM registrations WHERE date(created_at)=? AND status='done'", (d,))["c"]
    rx_today = q1("SELECT COUNT(*) c FROM prescriptions WHERE date(created_at)=?", (d,))["c"]
    income = q1("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions WHERE ttype='income' AND date(created_at)=?", (d,))["s"]
    pending_rx = q1("SELECT COUNT(*) c FROM prescriptions WHERE status='submitted'", ())["c"]
    waiting = q1("SELECT COUNT(*) c FROM registrations WHERE status IN ('waiting','called')", ())["c"]
    low_stock = q1("SELECT COUNT(*) c FROM (SELECT d.id FROM drugs d LEFT JOIN inventory i ON i.drug_id=d.id GROUP BY d.id HAVING COALESCE(SUM(i.qty),0) <= d.safe_stock)", ())["c"]
    near_expiry = q1("SELECT COUNT(*) c FROM inventory WHERE qty>0 AND expire_at<=?", ((today_iso(90),)))["c"]
    open_risks = q1("SELECT COUNT(*) c FROM risks WHERE status='open'", ())["c"]
    return {"date": d, "registrations": regs_today, "consulted": done_today, "prescriptions": rx_today,
            "income_cents": int(income), "pending_dispense": pending_rx, "waiting": waiting,
            "low_stock": low_stock, "near_expiry": near_expiry, "open_risks": open_risks}

def today_iso(days):
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()

# ---------- 平台域 ----------

def h_notices(ctx, m, qs, body):
    return listwrap("SELECT * FROM notices ORDER BY id DESC", (), qs)

def h_notices_create(ctx, m, qs, body):
    if not body.get("title"):
        raise ApiError(422, "title 必填")
    c = execute("INSERT INTO notices(title,content,level) VALUES(?,?,?)",
                (body["title"], body.get("content", ""), body.get("level", "info")))
    return {"id": c.lastrowid}

def h_notices_delete(ctx, m, qs, body):
    execute("DELETE FROM notices WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

def h_logs(ctx, m, qs, body):
    return listwrap("SELECT * FROM logs ORDER BY id DESC", (), qs)

def h_rules(ctx, m, qs, body):
    return {"items": [dict(r) for r in q("SELECT * FROM his_rules ORDER BY id")]}

def h_rules_update(ctx, m, qs, body):
    name = body.get("name")
    if not name:
        raise ApiError(422, "name 必填")
    if not q1("SELECT id FROM his_rules WHERE name=?", (name,)):
        execute("INSERT INTO his_rules(name,value,updated_at) VALUES(?,?,?)", (name, body.get("value", ""), now_s()))
    else:
        execute("UPDATE his_rules SET value=?, updated_at=? WHERE name=?", (body.get("value", ""), now_s(), name))
    return {"ok": True}

# ---------- 增量同步 / 导出 ----------

SYNC_ENTITIES = {
    "patients": "SELECT * FROM patients ORDER BY id",
    "doctors": "SELECT * FROM doctors ORDER BY id",
    "departments": "SELECT * FROM departments ORDER BY id",
    "schedules": "SELECT * FROM schedules ORDER BY id",
    "registrations": "SELECT * FROM registrations ORDER BY id",
    "prescriptions": "SELECT * FROM prescriptions ORDER BY id",
    "charges": "SELECT * FROM charges ORDER BY id",
    "inventory": "SELECT * FROM inventory ORDER BY id",
    "risks": "SELECT * FROM risks ORDER BY id",
}

def h_sync(ctx, m, qs, body):
    since = int(qs.get("since", ["0"])[0] or 0)
    ents = [e for e in (qs.get("entities", [""])[0] or "").split(",") if e]
    if not ents:
        ents = list(SYNC_ENTITIES.keys())
    changes, maxver = [], 0
    for e in ents:
        if e not in SYNC_ENTITIES:
            raise ApiError(422, "未知同步实体: %s" % e)
        v = get_sync(e)
        maxver = max(maxver, v)
        if v > since:
            rows = [dict(r) for r in q(SYNC_ENTITIES[e])]
            for r in rows:
                changes.append({"entity": e, "op": "upsert", "row": r})
    return {"version": maxver, "since": since, "changes": changes}

EXPORTS = {
    "patients": ("SELECT * FROM patients ORDER BY id", ["mrn", "name", "gender", "birth", "phone", "insurance_type"]),
    "registrations": ("SELECT * FROM registrations ORDER BY id", ["no", "patient_id", "doctor_id", "fee_cents", "status", "created_at"]),
    "prescriptions": ("SELECT * FROM prescriptions ORDER BY id", ["no", "patient_id", "status", "total_cents", "created_at"]),
    "charges": ("SELECT * FROM charges ORDER BY id", ["no", "patient_id", "total_cents", "discount_rate", "paid_cents", "pay_method", "status"]),
    "inventory": ("SELECT i.*, d.name FROM inventory i JOIN drugs d ON d.id=i.drug_id ORDER BY i.id", ["name", "batch_no", "qty", "expire_at"]),
    "transactions": ("SELECT * FROM transactions ORDER BY id", ["ttype", "amount_cents", "ref_type", "note", "created_at"]),
}

def h_export(ctx, m, qs, body):
    ent = m.group(1)
    if ent not in EXPORTS:
        raise ApiError(404, "未知导出实体")
    sql, cols = EXPORTS[ent]
    return ("csv", csv_export(q(sql), cols))

# ---------- 路由表 ----------

ROUTES = [
    ("GET",  r"^/api/health$", h_health, None),
    ("POST", r"^/api/login$", h_login, None),
    ("POST", r"^/api/logout$", h_logout, "auth"),
    ("GET",  r"^/api/me$", h_me, "auth"),
    ("GET",  r"^/api/users$", h_users, "admin"),
    ("POST", r"^/api/users$", h_users_create, "admin"),
    ("PUT",  r"^/api/users/(\d+)$", h_users_update, "admin"),
    ("GET",  r"^/api/api-keys$", h_keys, "admin"),
    ("POST", r"^/api/api-keys$", h_keys_create, "admin"),
    ("DELETE", r"^/api/api-keys/(\d+)$", h_keys_delete, "admin"),
    ("GET",  r"^/api/departments$", h_dept_list, "his.departments.read"),
    ("POST", r"^/api/departments$", h_dept_create, "his.departments.write"),
    ("PUT",  r"^/api/departments/(\d+)$", h_dept_update, "his.departments.write"),
    ("DELETE", r"^/api/departments/(\d+)$", h_dept_delete, "his.departments.write"),
    ("GET",  r"^/api/doctors$", h_doctor_list, "his.doctors.read"),
    ("POST", r"^/api/doctors$", h_doctor_create, "his.doctors.write"),
    ("GET",  r"^/api/doctors/(\d+)$", h_doctor_get, "his.doctors.read"),
    ("PUT",  r"^/api/doctors/(\d+)$", h_doctor_update, "his.doctors.write"),
    ("DELETE", r"^/api/doctors/(\d+)$", h_doctor_delete, "his.doctors.write"),
    ("GET",  r"^/api/patients$", h_patient_list, "his.patients.read"),
    ("POST", r"^/api/patients$", h_patient_create, "his.patients.write"),
    ("GET",  r"^/api/patients/(\d+)$", h_patient_get, "his.patients.read"),
    ("PUT",  r"^/api/patients/(\d+)$", h_patient_update, "his.patients.write"),
    ("DELETE", r"^/api/patients/(\d+)$", h_patient_delete, "his.patients.write"),
    ("GET",  r"^/api/patients/(\d+)/visits$", h_patient_visits, "his.patients.read"),
    ("GET",  r"^/api/drugs$", h_drug_list, "his.drugs.read"),
    ("POST", r"^/api/drugs$", h_drug_create, "his.drugs.write"),
    ("GET",  r"^/api/drugs/(\d+)$", h_drug_get, "his.drugs.read"),
    ("PUT",  r"^/api/drugs/(\d+)$", h_drug_update, "his.drugs.write"),
    ("DELETE", r"^/api/drugs/(\d+)$", h_drug_delete, "his.drugs.write"),
    ("GET",  r"^/api/suppliers$", h_supplier_list, "his.suppliers.read"),
    ("POST", r"^/api/suppliers$", h_supplier_create, "his.suppliers.write"),
    ("PUT",  r"^/api/suppliers/(\d+)$", h_supplier_update, "his.suppliers.write"),
    ("DELETE", r"^/api/suppliers/(\d+)$", h_supplier_delete, "his.suppliers.write"),
    ("GET",  r"^/api/schedules$", h_sched_list, "his.schedules.read"),
    ("POST", r"^/api/schedules$", h_sched_create, "his.schedules.write"),
    ("PUT",  r"^/api/schedules/(\d+)$", h_sched_update, "his.schedules.write"),
    ("DELETE", r"^/api/schedules/(\d+)$", h_sched_delete, "his.schedules.write"),
    ("GET",  r"^/api/registrations$", h_reg_list, "his.registrations.read"),
    ("POST", r"^/api/registrations$", h_reg_create, "his.registrations.write"),
    ("GET",  r"^/api/registrations/queue$", h_reg_queue, "his.registrations.read"),
    ("GET",  r"^/api/registrations/(\d+)$", h_reg_get, "his.registrations.read"),
    ("POST", r"^/api/registrations/(\d+)/transition$", h_reg_transition, "his.registrations.write"),
    ("GET",  r"^/api/clinic-records$", h_record_list, "his.clinic.read"),
    ("POST", r"^/api/clinic-records$", h_record_create, "his.clinic.write"),
    ("GET",  r"^/api/clinic-records/(\d+)$", h_record_get, "his.clinic.read"),
    ("PUT",  r"^/api/clinic-records/(\d+)$", h_record_update, "his.clinic.write"),
    ("GET",  r"^/api/prescriptions$", h_rx_list, "his.prescriptions.read"),
    ("POST", r"^/api/prescriptions$", h_rx_create, "his.prescriptions.write"),
    ("GET",  r"^/api/prescriptions/(\d+)$", h_rx_get, "his.prescriptions.read"),
    ("POST", r"^/api/prescriptions/(\d+)/transition$", h_rx_transition, "his.prescriptions.write"),
    ("GET",  r"^/api/charges$", h_charge_list, "his.charges.read"),
    ("POST", r"^/api/charges$", h_charge_create, "his.charges.write"),
    ("GET",  r"^/api/charges/(\d+)$", h_charge_get, "his.charges.read"),
    ("POST", r"^/api/charges/(\d+)/refund$", h_charge_refund, "his.charges.write"),
    ("GET",  r"^/api/pharmacy/pending$", h_pharmacy_pending, "his.pharmacy.read"),
    ("GET",  r"^/api/pharmacy/logs$", h_pharmacy_logs, "his.pharmacy.read"),
    ("GET",  r"^/api/inventory$", h_inv_list, "his.inventory.read"),
    ("GET",  r"^/api/inventory/summary$", h_inv_summary, "his.inventory.read"),
    ("GET",  r"^/api/purchases$", h_purchase_list, "his.purchases.read"),
    ("POST", r"^/api/purchases$", h_purchase_create, "his.purchases.write"),
    ("GET",  r"^/api/purchases/(\d+)$", h_purchase_get, "his.purchases.read"),
    ("DELETE", r"^/api/purchases/(\d+)$", h_purchase_delete, "his.purchases.write"),
    ("POST", r"^/api/purchases/(\d+)/items$", h_purchase_item_add, "his.purchases.write"),
    ("POST", r"^/api/purchases/(\d+)/transition$", h_purchase_transition, "his.purchases.write"),
    ("GET",  r"^/api/transactions$", h_tx_list, "his.transactions.read"),
    ("GET",  r"^/api/finance/summary$", h_finance_summary, "his.transactions.read"),
    ("GET",  r"^/api/risks$", h_risk_list, "his.risks.read"),
    ("POST", r"^/api/risks/scan$", h_risk_scan, "his.risks.write"),
    ("PUT",  r"^/api/risks/(\d+)/resolve$", h_risk_resolve, "his.risks.write"),
    ("GET",  r"^/api/dashboard$", h_dashboard, "auth"),
    ("GET",  r"^/api/notices$", h_notices, "auth"),
    ("POST", r"^/api/notices$", h_notices_create, "admin"),
    ("DELETE", r"^/api/notices/(\d+)$", h_notices_delete, "admin"),
    ("GET",  r"^/api/logs$", h_logs, "admin"),
    ("GET",  r"^/api/rules$", h_rules, "auth"),
    ("PUT",  r"^/api/rules$", h_rules_update, "admin"),
    ("GET",  r"^/api/sync$", h_sync, "auth"),
    ("GET",  r"^/api/export/([a-z]+)$", h_export, "auth"),
]

_COMPILED = [(mt, re.compile(rx), fn, perm) for mt, rx, fn, perm in ROUTES]

# ---------- HTTP Handler ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FeiYiHIS/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, data, ctype="application/json; charset=utf-8", extra=None):
        body = data if isinstance(data, bytes) else data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Token, X-Api-Key, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, code, data):
        if isinstance(data, str):
            self._send(code, jdump({"code": code, "message": data, "data": None}))
        else:
            self._send(code, jdump({"code": code, "message": "ok" if code < 400 else "error", "data": data}))

    def _body(self):
        ln = int(self.headers.get("Content-Length") or 0)
        if ln <= 0:
            return {}
        raw = self.rfile.read(ln)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _token_from_req(self):
        h = self.headers
        auth = h.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if h.get("X-Token"):
            return h["X-Token"].strip()
        ck = h.get("Cookie")
        if ck:
            try:
                c = http_cookies.SimpleCookie(ck)
                if "his_token" in c:
                    return c["his_token"].value
                if "token" in c:
                    return c["token"].value
            except Exception:
                pass
        if h.get("X-Api-Key"):
            return "key:" + h["X-Api-Key"].strip()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "token" in qs:
            return qs["token"][0]
        return None

    def _authenticate(self):
        tok = self._token_from_req()
        if not tok:
            return None, None
        if tok.startswith("key:"):
            u = auth_key(tok[4:])
            return ({"id": None, **u} if u else None), tok
        u = auth_token(tok)
        if u:
            perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"])
            return {"id": u["user_id"], "username": u["username"], "name": u["name"], "role": u["role"], "perms": perms}, tok
        return None, tok

    def _match_route(self, method, path):
        for mt, rx, fn, perm in _COMPILED:
            if mt != method:
                continue
            m = rx.match(path)
            if m:
                return fn, perm, m
        return None, None, None

    def _handle(self, method):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if PREFIX and path.startswith(PREFIX):
                path = path[len(PREFIX):] or "/"
            if method == "OPTIONS":
                return self._send(200, "{}")
            if not path.startswith("/api/"):
                return self._static(path)
            qs = urllib.parse.parse_qs(parsed.query)
            fn, perm, m = self._match_route(method, path)
            if not fn:
                return self._send_json(404, "接口不存在: %s" % path)
            user, tok = self._authenticate()
            ctx = {"user": user or {}, "token": (tok or "").replace("key:", "")}
            if perm is not None and not user:
                return self._send_json(401, "未认证")
            if perm == "admin":
                if not user or user.get("role") != "admin":
                    return self._send_json(403, "需要管理员权限")
            elif perm == "auth":
                if not user:
                    return self._send_json(401, "未认证")
            elif perm:
                perms = user.get("perms") if user else None
                if not user or not K.has_perm(perms or [], perm):
                    return self._send_json(403, "无权限: " + perm)
            body = self._body() if method in ("POST", "PUT", "DELETE") else {}
            idem = self.headers.get("Idempotency-Key")
            if idem and method == "POST":
                row = q1("SELECT response FROM idem_keys WHERE key=?", (idem,))
                if row:
                    return self._send(200, row["response"])
            result = fn(ctx, m, qs, body)
            if isinstance(result, tuple) and result[0] == "csv":
                return self._send(200, result[1], ctype="text/csv; charset=utf-8",
                                  extra={"Content-Disposition": "attachment; filename=export.csv"})
            payload = jdump({"code": 200, "message": "ok", "data": result})
            if idem and method == "POST":
                execute("INSERT OR REPLACE INTO idem_keys(key, user_id, response, created_at) VALUES(?,?,?,?)",
                        (idem, user.get("id") if user else None, payload, now_s()))
            return self._send(200, payload)
        except ApiError as e:
            return self._send_json(e.code, e.message)
        except Exception as e:
            traceback.print_exc()
            return self._send_json(500, "内部错误: %s" % e)

    def _static(self, path):
        if path in ("/", "/index.html", ""):
            path = "/index.html"
        fp = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend"), path.lstrip("/"))
        fp = os.path.normpath(fp)
        if not fp.startswith(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))):
            return self._send(403, "forbidden", ctype="text/plain")
        if not os.path.isfile(fp):
            return self._send(404, "not found", ctype="text/plain")
        ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon"}.get(fp.rsplit(".", 1)[-1], "application/octet-stream")
        with open(fp, "rb") as f:
            return self._send(200, f.read(), ctype=ctype)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self._handle("OPTIONS")

def main():
    D.init_db()
    S.run()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("FeiYi HIS listening on :%d prefix=%r db=%s" % (PORT, PREFIX, D.DB_PATH))
    srv.serve_forever()

if __name__ == "__main__":
    main()
