# -*- coding: utf-8 -*-
"""飞医 HIS · Playwright UI 巡检：登录 + 13 页面 + 控制台异常检查"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8028"
PAGES = ["dash", "patient", "doctor", "schedule", "registration", "clinic", "prescription",
         "charge", "pharmacy", "inventory", "supplier", "finance", "risk", "system"]

fails = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/login.html")
    pg.fill("#u", "admin")
    pg.fill("#p", "123456")
    pg.click("#go")
    pg.wait_for_url("**/index.html", timeout=8000)
    pg.wait_for_selector(".kpi", timeout=8000)
    print("OK   login + dash")
    for k in PAGES[1:]:
        pg.goto(BASE + "/index.html#/" + k)
        pg.wait_for_timeout(700)
        txt = pg.inner_text("#main")
        if len(txt.strip()) < 10 or "加载失败" in txt:
            fails.append(k)
            print("FAIL", k, txt[:120])
        else:
            print("OK  ", k)
    if errors:
        fails.append("js-errors")
        print("JS ERRORS:", errors[:5])
    b.close()

print("==== UI PASS=%d FAIL=%d ====" % (len(PAGES) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
