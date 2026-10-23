# -*- coding: utf-8 -*-
"""pytest 夹具：临时库 + 进程内 HTTP 服务"""
import os, sys, tempfile, threading, json, urllib.request, urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import pytest

@pytest.fixture(scope="session")
def srv():
    tmpdir = tempfile.mkdtemp(prefix="feiyi_test_")
    os.environ["HIS_DB"] = os.path.join(tmpdir, "test.db")
    for m in list([k for k in __import__("sys").modules if k in ("db", "his", "seed", "server")]):
        del __import__("sys").modules[m]
    import db as D
    import seed as S
    import server as SV
    D.DB_PATH = os.environ["HIS_DB"]
    D._local = __import__("threading").local()
    D.init_db()
    S.run()
    httpd = SV.ThreadingHTTPServer(("127.0.0.1", 0), SV.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield {"base": "http://127.0.0.1:%d" % httpd.server_address[1], "httpd": httpd}
    httpd.shutdown()

@pytest.fixture(scope="session")
def tok(srv):
    j = jreq(srv["base"], "POST", "/api/login", {"username": "admin", "password": "123456"})
    assert j["code"] == 200, j
    return j["data"]["token"]

def jreq(base, method, path, body=None, token=None, headers=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method, headers=h)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(r, timeout=15) as f:
            raw = f.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
    try:
        return json.loads(raw)
    except ValueError:
        return ("raw", raw)

@pytest.fixture(scope="session")
def jreq_fn(srv):
    base = srv["base"]
    def _jreq(method, path, body=None, token=None, headers=None):
        return jreq(base, method, path, body, token, headers)
    return _jreq
