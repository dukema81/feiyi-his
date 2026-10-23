# -*- coding: utf-8 -*-
"""飞医 DEMO 页面巡检：Playwright 加载本地单文件 HTML，13 页面检查"""
import os, sys
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = "file:///" + os.path.join(ROOT, "demo", "飞医医疗管理系统Demo.html").replace("\\", "/")
PAGES = ["dash", "patient", "doctor", "schedule", "registration", "clinic", "prescription",
         "charge", "pharmacy", "inventory", "supplier", "finance", "risk", "system"]

fails = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(HTML)
    pg.wait_for_timeout(1200)
    pg.wait_for_selector(".kpi", timeout=8000)
    print("OK   dash")
    for k in PAGES[1:]:
        pg.evaluate("location.hash = '#/%s'" % k)
        pg.wait_for_timeout(600)
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

print("==== DEMO PASS=%d FAIL=%d ====" % (len(PAGES) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
