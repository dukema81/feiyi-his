/* 飞医医疗管理系统 · 框架层 */
var TOKEN = localStorage.getItem('his_token') || '';
var ME = JSON.parse(localStorage.getItem('his_user') || '{}');
var PERMS = ME.perms || [];

function api(method, path, body, raw) {
  return fetch(PREFIX + path, {
    method: method,
    headers: Object.assign({'Content-Type': 'application/json'},
      TOKEN ? {Authorization: 'Bearer ' + TOKEN} : {}),
    body: (method === 'POST' || method === 'PUT' || method === 'DELETE') ? JSON.stringify(body || {}) : undefined
  }).then(function (r) {
    if (r.status === 401) { localStorage.clear(); location.href = 'login.html'; throw new Error('unauth'); }
    if (r.status >= 400) {
      return r.text().then(function (t) {
        var msg = 'HTTP ' + r.status;
        try { msg = (JSON.parse(t) || {}).message || msg; } catch (e) { /* 非 JSON */ }
        throw new Error(msg);
      });
    }
    return raw ? r.text() : r.json();
  }).then(function (j) {
    if (raw) return j;
    if (j && j.code && j.code !== 200) throw new Error(j.message || ('错误 ' + j.code));
    return j;
  });
}
function GET(p) { return api('GET', p); }
function POST(p, b) { return api('POST', p, b); }
function PUT(p, b) { return api('PUT', p, b); }
function DEL(p) { return api('DELETE', p); }
function CSV(p) { return api('GET', p, null, true); }

function toast(msg, err) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = err ? '#cf2f4b' : '#1c2340';
  t.classList.remove('hidden');
  clearTimeout(t._tm);
  t._tm = setTimeout(function () { t.classList.add('hidden'); }, 2600);
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
  });
}
function perm(p) { return PERMS.indexOf('*') >= 0 || PERMS.indexOf(p) >= 0; }

/* ---------- 格式化 ---------- */
function fmtMoney(n, noSym) {
  if (n == null || n === '') return '—';
  var v = Number(n);
  var s = Math.abs(v) >= 10000
    ? v.toLocaleString('zh-CN', {maximumFractionDigits: 2})
    : v.toFixed(2);
  return (noSym ? '' : '¥') + s;
}
/* 分 → 元 显示 */
function fmtCents(c, noSym) {
  if (c == null || c === '') return '—';
  return fmtMoney(Number(c) / 100, noSym);
}
function fmtPct(x, digits) {
  if (x == null || x === '') return '—';
  return (Number(x) * 100).toFixed(digits == null ? 0 : digits) + '%';
}
function todayStr() {
  var d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}

var NAV = [
  ['dash', '工作台', '◱'],
  ['patient', '患者管理', '☺'],
  ['doctor', '医生管理', '🩺'],
  ['schedule', '排班管理', '🗓'],
  ['registration', '门诊挂号', '🎫'],
  ['clinic', '门诊病历', '📋'],
  ['prescription', '处方管理', '℞'],
  ['charge', '收费结算', '¥'],
  ['pharmacy', '药房发药', '💊'],
  ['inventory', '药品库存', '❄'],
  ['supplier', '供应商', '⧉'],
  ['finance', '财务流水', '💰'],
  ['risk', '风险预警', '⚠'],
  ['system', '系统管理', '⚙']
];

function boot() {
  if (!TOKEN) { location.href = 'login.html'; return; }
  GET('/api/me').then(function (r) {
    ME = r.data || {}; PERMS = ME.perms || [];
    localStorage.setItem('his_user', JSON.stringify(ME));
    document.getElementById('who').textContent = ME.user.name + ' · ' + (ME.user.role || '');
    var nav = document.getElementById('nav');
    nav.innerHTML = NAV.map(function (n) {
      return '<a href="#/' + n[0] + '" data-k="' + n[0] + '">' +
        '<span class="ic">' + n[2] + '</span>' + n[1] + '</a>';
    }).join('');
    nav.onclick = function (e) {
      var a = e.target.closest('a'); if (!a) return;
      e.preventDefault();
      go(a.getAttribute('data-k'));
    };
    var key = (location.hash || '#/dash').replace('#/', '');
    go(PAGES[key] ? key : 'dash');
    document.getElementById('btn-logout').onclick = function () {
      POST('/api/logout').then(function () {
        localStorage.clear(); location.href = 'login.html';
      }).catch(function () { localStorage.clear(); location.href = 'login.html'; });
    };
    window.addEventListener('hashchange', function () {
      var k = (location.hash || '#/dash').replace('#/', '');
      if (PAGES[k] && k !== CUR) go(k);
    });
    if (perm('his.risks.read')) {
      GET('/api/dashboard').then(function (d) {
        var n = ((d.data || {}).open_risks) || 0;
        if (!n) return;
        var a = document.querySelector('#nav a[data-k="risk"]');
        if (a) a.insertAdjacentHTML('beforeend', '<b class="badge">' + n + '</b>');
      }).catch(function () {});
    }
  }).catch(function (e) {
    if (e.message !== 'unauth') location.href = 'login.html';
  });
}

var CUR = null;
function go(key) {
  CUR = key;
  if (location.hash !== '#/' + key) location.hash = '#/' + key;
  document.querySelectorAll('#nav a').forEach(function (a) {
    a.classList.toggle('on', a.getAttribute('data-k') === key);
  });
  var main = document.getElementById('main');
  main.innerHTML = '<div class="empty">加载中…</div>';
  var task;
  try {
    task = PAGES[key](main);
  } catch (e) {
    task = Promise.reject(e);
  }
  Promise.resolve(task).catch(function (e) {
    if (e && e.message === 'unauth') return;
    main.innerHTML = '<div class="empty">加载失败：' + esc(e && e.message) + '</div>';
  });
}

function modal(html, wide) {
  var mask = document.getElementById('modal-mask');
  var box = document.getElementById('modal');
  box.innerHTML = html;
  box.className = 'modal' + (wide ? ' wide' : '');
  mask.classList.remove('hidden');
  mask.onclick = function (e) { if (e.target === mask) closeModal(); };
}
function closeModal() {
  document.getElementById('modal-mask').classList.add('hidden');
}

function table(headers, rows, rowHtml, empty) {
  if (!rows || !rows.length) return '<div class="empty">' + (empty || '暂无数据') + '</div>';
  return '<div class="tw"><table><thead><tr>' + headers.map(function (h) {
    if (h && h.charAt(0) === '~') return '<th class="num">' + h.slice(1) + '</th>';
    return '<th>' + h + '</th>';
  }).join('') + '</tr></thead><tbody>' + rows.map(rowHtml).join('') + '</tbody></table></div>';
}

function tag(text, cls) {
  return '<span class="tag ' + (cls || '') + '">' + esc(text) + '</span>';
}
var REG_TAG = {'waiting': ['候诊中', ''], 'called': ['已叫号', 'pri'], 'in_consult': ['接诊中', 'pri'],
               'done': ['已完成', 'ok'], 'cancelled': ['已退号', 'err']};
function regTag(s) {
  var m = REG_TAG[s] || [s, ''];
  return tag(m[0], m[1]);
}
var RX_TAG = {'draft': ['草稿', ''], 'submitted': ['已提交', 'pri'], 'dispensed': ['已发药', 'ok'],
              'cancelled': ['已作废', 'err']};
function rxTag(s) {
  var m = RX_TAG[s] || [s, ''];
  return tag(m[0], m[1]);
}
function insuranceTag(t) {
  var m = {'employee': ['职工医保', 'pri'], 'resident': ['居民医保', 'ok'], 'self': ['自费', '']};
  var x = m[t] || [t, ''];
  return tag(x[0], x[1]);
}
function levelTag(g) {
  var m = {'risk': '高风险', 'warn': '警告', 'info': '提示'};
  return tag(m[g] || g, g === 'risk' ? 'err' : (g === 'warn' ? 'warn' : ''));
}
function kpi(v, label, cls) {
  return '<div class="kpi ' + (cls || '') + '"><b>' + esc(v) + '</b><span>' + esc(label) + '</span></div>';
}
function field(label, input, hint) {
  return '<label class="fld"><span>' + esc(label) + '</span>' + input +
    (hint ? '<i>' + esc(hint) + '</i>' : '') + '</label>';
}
function bar(pct, cls) {
  var w = Math.max(0, Math.min(100, pct));
  return '<div class="bar"><i class="' + (cls || '') + '" style="width:' + w + '%"></i></div>';
}
function dl(p, name) {
  CSV(p).then(function (t) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([t], {type: 'text/csv;charset=utf-8'}));
    a.download = name || 'export.csv';
    a.click();
  }).catch(function (e) { toast(e.message, true); });
}
function qs(o) {
  var k = Object.keys(o || {}).filter(function (x) { return o[x]; });
  if (!k.length) return '';
  return '?' + k.map(function (x) { return x + '=' + encodeURIComponent(o[x]); }).join('&');
}
