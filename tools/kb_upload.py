# -*- coding: utf-8 -*-
"""飞医医疗管理系统 · 文档与DEMO批量上传知识库（分类 33 企业管理系统）"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = r"C:/Users/maxl/WorkBuddy/Claw/feiyi-his"
BASE = "http://42.193.158.63"
CAT = 33
PASSWORD = "YCSpyVwt@J2UByom3#n6gb"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
REPLACE = "--replace" in sys.argv

DOCS = [
    ("docs/feiyi_design_v1.docx", "飞医医疗管理系统建设方案",
     "「飞医医疗管理系统（HIS）」完整建设方案 V1.0：中小门诊数字化痛点与建设目标、"
     "业务域设计（科室/医生/患者档案/排班冲突检测/挂号状态机 waiting→called→in_consult→done/"
     "门诊病历/处方剂量校验/收费医保折扣 职工85%·居民65%/药房FEFO发药/批次效期库存/采购入库/"
     "供应商应付/五类风险预警 低库存·临期·剂量超限·排班冲突·挂号超时）、"
     "计算内核口径（金额以分存储、Decimal HALF_UP、医保折扣一次量化）、"
     "总体架构与零依赖技术选型（Python 标准库 http.server + SQLite WAL）、"
     "27 表数据模型、7 角色权限矩阵、14 页面功能清单、对外集成方案、部署方案。",
     "飞医,HIS,医疗管理,建设方案,门诊"),
    ("docs/feiyi_api_v1.docx", "飞医医疗管理系统 REST 接口契约",
     "82 端点分组契约：统一响应包 {code,message,data} 与 HTTP 状态一致、鉴权五通道"
     "（Bearer / X-Token / Cookie / ?token= / X-Api-Key，SHA-256 存储）、"
     "Idempotency-Key 幂等、增量同步协议（版本号 + 实体过滤）、列表统一 {items,total,page,size}、"
     "科室/医生/患者/药品/供应商/排班/挂号/病历/处方/收费/药房/库存/采购/财务/风险/平台域 全量接口表、"
     "挂号/处方/采购状态机约束、校验规则与错误码表、医保/LIS/企业系统对接示例。",
     "飞医,HIS,API,接口契约,REST,幂等,增量同步,医疗对接"),
    ("docs/feiyi_test_v1.docx", "飞医医疗管理系统测试报告",
     "三道质量门禁全部通过：pytest 55 条（内核 30 例：元转分HALF_UP/处方金额/医保折扣取整/"
     "挂号处方采购状态机/排班冲突/FEFO批次分配/剂量校验/风险规则/权限通配/统计；"
     "API 集成 25 例：挂号全流程/病历唯一/处方剂量告警/发药扣库存与不足回滚/医保折扣收费/"
     "重复收费409/退费/采购入库应付/风险扫描/幂等/增量同步/CSV导出/RBAC越权）；"
     "UI 巡检 Playwright 登录+14 页面 0 控制台异常；冒烟 70 项全通过（幂等化可重复执行）。"
     "测试中发现并修复多项缺陷（密码哈希不一致、元转分漏×100、has_perm 列表崩溃、序号未初始化等）。",
     "飞医,HIS,测试报告,pytest,Playwright,质量门禁"),
    ("docs/feiyi_manual_v1.docx", "飞医医疗管理系统使用手册",
     "面向全部 7 角色的操作手册：系统定位与账号表（admin/123456 等）、14 页面逐页说明"
     "（工作台 KPI、患者建档就诊史、医生档案、排班号源、挂号叫号退号、门诊病历、"
     "处方开立剂量校验、收费医保折扣退费、药房FEFO发药、药品批次库存、供应商应付、"
     "财务流水、风险四类扫描、系统管理密钥同步）、开一次门诊五步上手、金额分口径说明、"
     "医保/LIS/ERP 对接指引、部署运维、FAQ 四条。",
     "飞医,HIS,使用手册,操作指南,医疗管理"),
    ("demo/飞医医疗管理系统Demo.zip", "飞医医疗管理系统离线演示（DEMO）",
     "单文件离线演示（zip 内为 HTML，解压后双击即可用浏览器打开，无需服务与网络）。"
     "数据取自演示实例真实快照：8 用户 / 5 科室 / 5 医生 / 6 患者 / 6 药品 / 批次库存 / "
     "完整就诊链路（挂号→病历→处方→发药→收费）/ 采购单 / 财务流水 / 风险记录。"
     "14 个页签覆盖工作台、患者管理、医生管理、排班管理、门诊挂号、门诊病历、处方管理、"
     "收费结算、药房发药、药品库存、供应商、财务流水、风险预警、系统管理。"
     "支持顶部切换 4 个真实视角（管理员 / 医生 / 收费员 / 只读）。只读快照，写操作不会真正执行。",
     "飞医,HIS,DEMO,离线演示,医疗管理"),
]


def req(path, method="GET", data=None, token=None):
    r = urllib.request.Request(BASE + path, method=method)
    if data is not None:
        r.data = json.dumps(data).encode("utf-8")
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with OP.open(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                     # noqa: BLE001
            return e.code, {}


def curl_upload(path, title, desc, tags):
    full = os.path.join(ROOT, path)
    if full.endswith(".docx"):
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        mime = "application/zip"
    cmd = ["curl", "-s", "--noproxy", "*",
           "-H", "Authorization: Bearer " + TOKEN,
           "-F", "file=@%s;type=%s" % (full, mime),
           "-F", "title=" + title,
           "-F", "description=" + desc,
           "-F", "categoryId=%d" % CAT,
           "-F", "tags=" + tags,
           BASE + "/api/documents/upload"]
    out = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:                                         # noqa: BLE001
        return {"code": -1, "raw": out.stdout.decode("utf-8", "ignore")[:400],
                "err": out.stderr.decode("utf-8", "ignore")[:200]}


def existing(cat=CAT):
    st, j = req("/api/documents?categoryId=%d&pageNum=1&pageSize=200" % cat, token=TOKEN)
    data = j.get("data") or {}
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("list") or []


def delete_doc(doc_id):
    return req("/api/documents/%s" % doc_id, "DELETE", token=TOKEN)


def main():
    global TOKEN
    st, j = req("/api/auth/login", "POST", {"username": "admin", "password": PASSWORD})
    assert j.get("code") == 200, j
    TOKEN = j["data"]["token"]
    print("login ok")

    if REPLACE:
        want = {t for _, t, _, _ in DOCS}
        for r in existing():
            if r.get("title") in want:
                st, j = delete_doc(r.get("id"))
                print("删除旧文档 %s id=%s -> %s" % (r.get("title"), r.get("id"), st))
                time.sleep(0.4)

    results = []
    for path, title, desc, tags in DOCS:
        j = curl_upload(path, title, desc, tags)
        code = j.get("code")
        doc_id = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else j.get("data")
        size = os.path.getsize(os.path.join(ROOT, path))
        print("%-32s code=%s id=%s %.1fKB" % (os.path.basename(path), code, doc_id, size / 1024.0))
        if code != 200:
            print("   !!", str(j)[:300])
        results.append((path, title, code, doc_id))
        time.sleep(1.2)

    ok = [r for r in results if r[2] == 200]
    print("\n上传成功 %d / %d" % (len(ok), len(results)))
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "kb_upload_result.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": r[0], "title": r[1], "code": r[2], "id": r[3]} for r in results],
                  f, ensure_ascii=False, indent=2)
    return results


if __name__ == "__main__":
    main()
