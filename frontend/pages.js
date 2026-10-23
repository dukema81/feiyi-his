/* 飞医医疗管理系统 · 页面层 */
var PAGES = {};

/* ---------- 工作台 ---------- */
PAGES.dash = function (main) {
  return GET('/api/dashboard').then(function (r) {
    var d = r.data || {};
    main.innerHTML =
      '<h2>工作台</h2>' +
      '<div class="kpis">' +
      kpi(d.registrations, '今日挂号') +
      kpi(d.consulted, '今日接诊') +
      kpi(d.prescriptions, '今日处方') +
      kpi(fmtCents(d.income_cents), '今日收入', 'ok') +
      kpi(d.pending_dispense, '待发药处方', d.pending_dispense ? 'warn' : '') +
      kpi(d.waiting, '候诊人数', d.waiting ? 'warn' : '') +
      kpi(d.low_stock, '低库存药品', d.low_stock ? 'warn' : '') +
      kpi(d.near_expiry, '临期批次', d.near_expiry ? 'warn' : '') +
      kpi(d.open_risks, '未处理风险', d.open_risks ? 'err' : '') +
      '</div>' +
      '<div class="grid2">' +
      '<div class="card"><h3>候诊队列</h3><div id="dash-queue">加载中…</div></div>' +
      '<div class="card"><h3>快捷操作</h3><div class="quick">' +
      (perm('his.registrations.write') ? '<a class="btn" href="#/registration">门诊挂号</a>' : '') +
      (perm('his.prescriptions.write') ? '<a class="btn ghost" href="#/prescription">开处方</a>' : '') +
      (perm('his.pharmacy.read') ? '<a class="btn ghost" href="#/pharmacy">药房发药</a>' : '') +
      (perm('his.charges.write') ? '<a class="btn ghost" href="#/charge">收费结算</a>' : '') +
      '</div></div></div>';
    return GET('/api/registrations/queue').then(function (r2) {
      var el = document.getElementById('dash-queue');
      if (el) el.innerHTML = table(['排队号', '患者', '医生', '状态'], (r2.data.items || []).slice(0, 8), function (x) {
        return '<tr><td class="num">' + x.no_in_queue + '</td><td>' + esc(x.patient_name || '') + '</td>' +
          '<td>' + esc(x.doctor_name || '') + '</td><td>' + regTag(x.status) + '</td></tr>';
      }, '当前无人候诊');
    });
  });
};

/* ---------- 患者管理 ---------- */
PAGES.patient = function (main) {
  main.innerHTML = '<h2>患者管理</h2><div class="toolbar">' +
    (perm('his.patients.write') ? '<button class="btn" id="btn-new">建档</button>' : '') +
    '<input id="f-kw" placeholder="姓名/档案号/手机号" class="inp">' +
    '<button class="btn ghost" id="btn-search">搜索</button>' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  if (document.getElementById('btn-export'))
    document.getElementById('btn-export').onclick = function () { dl('/api/export/patients', 'patients.csv'); };
  function load(kw) {
    GET('/api/patients' + qs({keyword: kw})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['档案号', '姓名', '性别', '出生日期', '电话', '过敏史', '医保', '操作'], r.data.items, function (x) {
          var ops = '';
          if (perm('his.patients.read')) ops += '<button class="btn sm ghost" data-visits="' + x.id + '">就诊史</button>';
          return '<tr><td>' + esc(x.mrn) + '</td><td>' + esc(x.name) + '</td>' +
            '<td>' + (x.gender === 'M' ? '男' : '女') + '</td><td>' + esc(x.birth || '—') + '</td>' +
            '<td>' + esc(x.phone || '—') + '</td><td>' + esc(x.allergy || '—') + '</td>' +
            '<td>' + insuranceTag(x.insurance_type) + '</td><td class="ops">' + (ops || '—') + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b || !b.getAttribute('data-visits')) return;
        GET('/api/patients/' + b.getAttribute('data-visits') + '/visits').then(function (r2) {
          var items = r2.data.items || [];
          modal('<h3>就诊史</h3>' + table(['挂号号', '时间', '~挂号费', '状态', '病历/处方'], items, function (v) {
            var brief = (v.record && (v.record.diagnosis || v.record.chief_complaint)) ? esc(v.record.diagnosis || v.record.chief_complaint) : '—';
            if (v.prescriptions && v.prescriptions.length) brief += '（' + v.prescriptions.length + ' 张处方）';
            return '<tr><td>' + esc(v.no) + '</td><td>' + esc(v.created_at) + '</td>' +
              '<td class="num">' + fmtCents(v.fee_cents) + '</td><td>' + regTag(v.status) + '</td><td>' + brief + '</td></tr>';
          }, '暂无就诊记录', ) +
          '<div class="m-foot"><button class="btn ghost" onclick="closeModal()">关闭</button></div>', true);
        });
      };
    });
  }
  document.getElementById('btn-search').onclick = function () { load(document.getElementById('f-kw').value.trim()); };
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      modal('<h3>患者建档</h3>' +
        field('姓名', '<input id="f-name">') +
        field('性别', '<select id="f-gender"><option value="M">男</option><option value="F">女</option></select>') +
        field('出生日期', '<input id="f-birth" type="date">') +
        field('电话', '<input id="f-phone">') +
        field('过敏史', '<input id="f-allergy" placeholder="无">') +
        field('医保类型', '<select id="f-itype"><option value="self">自费</option>' +
          '<option value="employee">职工医保（85%）</option><option value="resident">居民医保（65%）</option></select>') +
        field('医保号', '<input id="f-ino" placeholder="自费可不填">') +
        '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
        '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('btn-ok').onclick = function () {
        POST('/api/patients', {
          name: document.getElementById('f-name').value.trim(),
          gender: document.getElementById('f-gender').value,
          birth: document.getElementById('f-birth').value || null,
          phone: document.getElementById('f-phone').value.trim(),
          allergy: document.getElementById('f-allergy').value.trim(),
          insurance_type: document.getElementById('f-itype').value,
          insurance_no: document.getElementById('f-ino').value.trim()
        }).then(function (r2) { toast('建档成功：' + r2.data.mrn); closeModal(); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    };
  load();
};

/* ---------- 医生管理 ---------- */
PAGES.doctor = function (main) {
  main.innerHTML = '<h2>医生管理</h2><div class="toolbar">' +
    (perm('his.doctors.write') ? '<button class="btn" id="btn-new">新增医生</button>' : '') +
    '</div><div id="list"></div>';
  function load() {
    GET('/api/doctors').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['姓名', '科室', '职称', '专长', '~挂号费'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.name) + '</td><td>' + esc(x.dept_name || '') + '</td>' +
            '<td>' + esc(x.title || '') + '</td><td>' + esc(x.specialty || '—') + '</td>' +
            '<td class="num">' + fmtCents(x.fee_cents) + '</td></tr>';
        });
    });
  }
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      GET('/api/departments').then(function (r) {
        modal('<h3>新增医生</h3>' +
          field('姓名', '<input id="f-name">') +
          field('科室', '<select id="f-dept">' + r.data.items.map(function (d) {
            return '<option value="' + d.id + '">' + esc(d.name) + '</option>';
          }).join('') + '</select>') +
          field('职称', '<select id="f-title"><option>主任医师</option><option>副主任医师</option>' +
            '<option>主治医师</option><option>住院医师</option></select>') +
          field('挂号费(元)', '<input id="f-fee" type="number" step="0.01" value="10">') +
          field('专长', '<input id="f-spec">') +
          '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
          '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
        document.getElementById('btn-ok').onclick = function () {
          POST('/api/doctors', {
            name: document.getElementById('f-name').value.trim(),
            dept_id: Number(document.getElementById('f-dept').value),
            title: document.getElementById('f-title').value,
            fee: Number(document.getElementById('f-fee').value),
            specialty: document.getElementById('f-spec').value.trim()
          }).then(function () { toast('已保存'); closeModal(); load(); })
            .catch(function (e) { toast(e.message, true); });
        };
      });
    };
  load();
};

/* ---------- 排班管理 ---------- */
PAGES.schedule = function (main) {
  main.innerHTML = '<h2>排班管理</h2><div class="toolbar">' +
    (perm('his.schedules.write') ? '<button class="btn" id="btn-new">新增排班</button>' : '') +
    '</div><div id="list"></div>';
  function load() {
    GET('/api/schedules').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['日期', '时段', '医生', '职称', '~号源', '~已约', '余号'], r.data.items, function (x) {
          var left = x.quota - x.booked;
          return '<tr><td>' + esc(x.sched_date) + '</td><td>' + (x.period === 'AM' ? '上午' : '下午') + '</td>' +
            '<td>' + esc(x.doctor_name || '') + '</td><td>' + esc(x.doctor_title || '') + '</td>' +
            '<td class="num">' + x.quota + '</td><td class="num">' + x.booked + '</td>' +
            '<td>' + (left > 0 ? tag(left + ' 个', 'ok') : tag('约满', 'err')) + '</td></tr>';
        });
    });
  }
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      GET('/api/doctors').then(function (r) {
        modal('<h3>新增排班</h3>' +
          field('医生', '<select id="f-doc">' + r.data.items.map(function (d) {
            return '<option value="' + d.id + '">' + esc(d.name) + '（' + esc(d.dept_name || '') + '）</option>';
          }).join('') + '</select>') +
          field('日期', '<input id="f-date" type="date" value="' + todayStr() + '">') +
          field('时段', '<select id="f-period"><option value="AM">上午</option><option value="PM">下午</option></select>') +
          field('号源', '<input id="f-quota" type="number" value="20" min="1">') +
          '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
          '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
        document.getElementById('btn-ok').onclick = function () {
          POST('/api/schedules', {
            doctor_id: Number(document.getElementById('f-doc').value),
            sched_date: document.getElementById('f-date').value,
            period: document.getElementById('f-period').value,
            quota: Number(document.getElementById('f-quota').value)
          }).then(function () { toast('排班已创建'); closeModal(); load(); })
            .catch(function (e) { toast(e.message, true); });
        };
      });
    };
  load();
};

/* ---------- 门诊挂号 ---------- */
PAGES.registration = function (main) {
  main.innerHTML = '<h2>门诊挂号</h2><div class="toolbar">' +
    (perm('his.registrations.write') ? '<button class="btn" id="btn-new">挂号</button>' : '') +
    '<select id="f-status"><option value="">全部状态</option>' +
    '<option value="waiting">候诊中</option><option value="called">已叫号</option>' +
    '<option value="in_consult">接诊中</option><option value="done">已完成</option><option value="cancelled">已退号</option></select>' +
    '<button class="btn ghost" id="btn-filter">筛选</button>' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  if (document.getElementById('btn-export'))
    document.getElementById('btn-export').onclick = function () { dl('/api/export/registrations', 'registrations.csv'); };
  function actBtn(x) {
    if (!perm('his.registrations.write')) return '—';
    var m = {'waiting': [['to_called', '叫号'], ['to_cancelled', '退号']],
             'called': [['to_in_consult', '接诊'], ['to_cancelled', '退号']],
             'in_consult': [['to_done', '完成']]};
    return (m[x.status] || []).map(function (a) {
      return '<button class="btn sm ghost" data-id="' + x.id + '" data-act="' + a[0] + '">' + a[1] + '</button>';
    }).join(' ') || '—';
  }
  function load(st) {
    GET('/api/registrations' + qs({status: st})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['挂号号', '时间', '状态', '~挂号费', '已收费', '操作'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.no) + '</td><td>' + esc(x.created_at) + '</td><td>' + regTag(x.status) + '</td>' +
            '<td class="num">' + fmtCents(x.fee_cents) + '</td>' +
            '<td>' + (x.paid ? tag('已收费', 'ok') : tag('未收费', 'warn')) + '</td>' +
            '<td class="ops">' + actBtn(x) + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b) return;
        POST('/api/registrations/' + b.getAttribute('data-id') + '/transition', {action: b.getAttribute('data-act')})
          .then(function () { toast('操作成功'); load(document.getElementById('f-status').value); })
          .catch(function (e2) { toast(e2.message, true); });
      };
    });
  }
  document.getElementById('btn-filter').onclick = function () { load(document.getElementById('f-status').value); };
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      Promise.all([GET('/api/patients'), GET('/api/schedules')]).then(function (rs) {
        var open = (rs[1].data.items || []).filter(function (s) { return s.status === 'open' && s.quota > s.booked; });
        modal('<h3>门诊挂号</h3>' +
          field('患者', '<select id="f-pat">' + rs[0].data.items.map(function (p) {
            return '<option value="' + p.id + '">' + esc(p.name) + '（' + esc(p.mrn) + '）</option>';
          }).join('') + '</select>') +
          field('排班', '<select id="f-sched">' + open.map(function (s) {
            return '<option value="' + s.id + '">' + esc(s.sched_date) + ' ' + (s.period === 'AM' ? '上午' : '下午') +
              ' ' + esc(s.doctor_name || '') + '（余 ' + (s.quota - s.booked) + '）</option>';
          }).join('') + '</select>', open.length ? '' : '暂无可约排班') +
          '<div class="m-foot"><button class="btn" id="btn-ok">确认挂号</button>' +
          '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
        document.getElementById('btn-ok').onclick = function () {
          POST('/api/registrations', {
            patient_id: Number(document.getElementById('f-pat').value),
            schedule_id: Number(document.getElementById('f-sched').value)
          }).then(function (r2) {
            toast('挂号成功：' + r2.data.no + '，挂号费 ' + fmtCents(r2.data.fee_cents));
            closeModal(); load();
          }).catch(function (e) { toast(e.message, true); });
        };
      });
    };
  load();
};

/* ---------- 门诊病历 ---------- */
PAGES.clinic = function (main) {
  main.innerHTML = '<h2>门诊病历</h2><div id="list"></div>';
  function load() {
    GET('/api/clinic-records').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['#', '~挂号单', '主诉', '诊断', '处理意见', '时间'], r.data.items, function (x) {
          return '<tr><td>' + x.id + '</td><td class="num">' + x.registration_id + '</td>' +
            '<td>' + esc(x.chief_complaint || '—') + '</td><td>' + esc(x.diagnosis || '—') + '</td>' +
            '<td>' + esc(x.advice || '—') + '</td><td>' + esc(x.created_at) + '</td></tr>';
        });
    });
  }
  load();
};

/* ---------- 处方管理 ---------- */
PAGES.prescription = function (main) {
  main.innerHTML = '<h2>处方管理</h2><div class="toolbar">' +
    (perm('his.prescriptions.write') ? '<button class="btn" id="btn-new">开处方</button>' : '') +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  if (document.getElementById('btn-export'))
    document.getElementById('btn-export').onclick = function () { dl('/api/export/prescriptions', 'prescriptions.csv'); };
  function actBtn(x) {
    if (!perm('his.prescriptions.write')) return '—';
    var m = {'draft': [['to_submitted', '提交']],
             'submitted': [['to_dispensed', '发药'], ['to_cancelled', '作废']]};
    return (m[x.status] || []).map(function (a) {
      return '<button class="btn sm ghost" data-id="' + x.id + '" data-act="' + a[0] + '">' + a[1] + '</button>';
    }).join(' ') || '—';
  }
  function load() {
    GET('/api/prescriptions').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['处方号', '时间', '状态', '~金额', '操作'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.no) + '</td><td>' + esc(x.created_at) + '</td><td>' + rxTag(x.status) + '</td>' +
            '<td class="num">' + fmtCents(x.total_cents) + '</td><td class="ops">' + actBtn(x) + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b) return;
        var id = b.getAttribute('data-id'), act = b.getAttribute('data-act');
        if (act === 'view') return;
        POST('/api/prescriptions/' + id + '/transition', {action: act})
          .then(function (r2) {
            toast(act === 'to_dispensed' ? '发药成功，库存已扣减' : '操作成功');
            load();
          }).catch(function (e2) { toast(e2.message, true); });
      };
    });
  }
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      Promise.all([GET('/api/patients'), GET('/api/doctors'), GET('/api/drugs')]).then(function (rs) {
        var drugs = rs[2].data.items;
        modal('<h3>开处方</h3>' +
          field('患者', '<select id="f-pat">' + rs[0].data.items.map(function (p) {
            return '<option value="' + p.id + '">' + esc(p.name) + '（' + esc(p.mrn) + '）</option>';
          }).join('') + '</select>') +
          field('医生', '<select id="f-doc">' + rs[1].data.items.map(function (d) {
            return '<option value="' + d.id + '">' + esc(d.name) + '</option>';
          }).join('') + '</select>') +
          '<div id="rx-items"></div>' +
          '<div class="toolbar"><button class="btn sm ghost" id="btn-add-item">＋ 添加药品</button></div>' +
          '<div class="m-foot"><button class="btn" id="btn-ok">保存处方</button>' +
          '<button class="btn ghost" onclick="closeModal()">取消</button></div>', true);
        var n = 0;
        function addItem() {
          n++;
          document.getElementById('rx-items').insertAdjacentHTML('beforeend',
            '<div class="fld-row" data-row="' + n + '">' +
            '<select class="i-drug">' + drugs.map(function (d) {
              return '<option value="' + d.id + '">' + esc(d.name) + ' ' + fmtCents(d.price_cents) + '</option>';
            }).join('') + '</select>' +
            '<input class="i-dose" type="number" step="0.01" placeholder="剂量" style="width:80px">' +
            '<input class="i-freq" placeholder="用法 如 tid" style="width:90px">' +
            '<input class="i-days" type="number" value="1" min="1" placeholder="天数" style="width:70px">' +
            '<input class="i-qty" type="number" value="1" min="1" placeholder="数量" style="width:70px">' +
            '</div>');
        }
        addItem();
        document.getElementById('btn-add-item').onclick = addItem;
        document.getElementById('btn-ok').onclick = function () {
          var items = [];
          document.querySelectorAll('#rx-items .fld-row').forEach(function (row) {
            items.push({
              drug_id: Number(row.querySelector('.i-drug').value),
              dose: Number(row.querySelector('.i-dose').value || 0),
              frequency: row.querySelector('.i-freq').value.trim(),
              days: Number(row.querySelector('.i-days').value || 1),
              qty: Number(row.querySelector('.i-qty').value || 1)
            });
          });
          POST('/api/prescriptions', {
            patient_id: Number(document.getElementById('f-pat').value),
            doctor_id: Number(document.getElementById('f-doc').value),
            items: items
          }).then(function (r2) {
            toast('处方已保存：' + r2.data.no + '，金额 ' + fmtCents(r2.data.total_cents));
            closeModal(); load();
          }).catch(function (e) { toast(e.message, true); });
        };
      });
    };
  load();
};

/* ---------- 收费结算 ---------- */
PAGES.charge = function (main) {
  main.innerHTML = '<h2>收费结算</h2><div class="toolbar">' +
    (perm('his.charges.write') ? '<button class="btn" id="btn-new">收费</button>' : '') +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  if (document.getElementById('btn-export'))
    document.getElementById('btn-export').onclick = function () { dl('/api/export/charges', 'charges.csv'); };
  function load() {
    GET('/api/charges').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['收费号', '时间', '~总额', '~折扣', '~实收', '方式', '状态', '操作'], r.data.items, function (x) {
          var ops = '';
          if (perm('his.charges.write') && x.status === 'paid')
            ops = '<button class="btn sm ghost" data-ref="' + x.id + '">退费</button>';
          return '<tr><td>' + esc(x.no) + '</td><td>' + esc(x.created_at) + '</td>' +
            '<td class="num">' + fmtCents(x.total_cents) + '</td><td class="num">' + fmtPct(x.discount_rate) + '</td>' +
            '<td class="num">' + fmtCents(x.paid_cents) + '</td><td>' + esc(x.pay_method) + '</td>' +
            '<td>' + tag(x.status === 'paid' ? '已支付' : '已退费', x.status === 'paid' ? 'ok' : 'err') + '</td>' +
            '<td class="ops">' + (ops || '—') + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b || !b.getAttribute('data-ref')) return;
        var id = b.getAttribute('data-ref');
        POST('/api/charges/' + id + '/refund', {}).then(function (r2) {
          toast('退费成功：' + fmtCents(r2.data.refund_cents)); load();
        }).catch(function (e2) { toast(e2.message, true); });
      };
    });
  }
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      Promise.all([GET('/api/registrations?status=done'), GET('/api/prescriptions')]).then(function (rs) {
        var regs = (rs[0].data.items || []).filter(function (x) { return !x.paid; });
        var rxs = (rs[1].data.items || []).filter(function (x) { return x.status === 'submitted' || x.status === 'dispensed' || x.status === 'draft'; });
        modal('<h3>收费结算</h3>' +
          field('挂号单（挂号费）', '<select id="f-reg"><option value="">不收挂号费</option>' + regs.map(function (x) {
            return '<option value="' + x.id + '">' + esc(x.no) + ' ' + fmtCents(x.fee_cents) + '</option>';
          }).join('') + '</select>') +
          '<div class="fld"><span>处方（可多选）</span><select id="f-rxs" multiple size="5">' + rxs.map(function (x) {
            return '<option value="' + x.id + '">' + esc(x.no) + ' ' + fmtCents(x.total_cents) + '</option>';
          }).join('') + '</select></div>' +
          field('支付方式', '<select id="f-pay"><option value="cash">现金</option><option value="wechat">微信</option>' +
            '<option value="alipay">支付宝</option><option value="insurance">医保</option></select>') +
          '<div class="m-foot"><button class="btn" id="btn-ok">确认收款</button>' +
          '<button class="btn ghost" onclick="closeModal()">取消</button></div>', true);
        document.getElementById('btn-ok').onclick = function () {
          var sel = document.getElementById('f-rxs');
          var rxids = [];
          for (var i = 0; i < sel.options.length; i++) if (sel.options[i].selected) rxids.push(Number(sel.options[i].value));
          var regv = document.getElementById('f-reg').value;
          POST('/api/charges', {
            registration_id: regv ? Number(regv) : null,
            prescription_ids: rxids,
            pay_method: document.getElementById('f-pay').value
          }).then(function (r2) {
            toast('收费成功：' + r2.data.no + '，实收 ' + fmtCents(r2.data.paid_cents));
            closeModal(); load();
          }).catch(function (e) { toast(e.message, true); });
        };
      });
    };
  load();
};

/* ---------- 药房发药 ---------- */
PAGES.pharmacy = function (main) {
  main.innerHTML = '<h2>药房发药</h2><div class="toolbar">' +
    '<button class="btn ghost" onclick="location.reload()">刷新</button></div>' +
    '<div class="card"><h3>待发药处方</h3><div id="pending"></div></div>' +
    '<div class="card"><h3>发药记录</h3><div id="logs"></div></div>';
  Promise.all([GET('/api/pharmacy/pending'), GET('/api/pharmacy/logs')]).then(function (rs) {
    document.getElementById('pending').innerHTML = table(
      ['处方号', '~金额', '~明细数', '操作'], rs[0].data.items, function (x) {
        var ops = perm('his.prescriptions.write')
          ? '<button class="btn sm ok" data-disp="' + x.id + '">发药</button>' : '—';
        return '<tr><td>' + esc(x.no) + '</td><td class="num">' + fmtCents(x.total_cents) + '</td>' +
          '<td class="num">' + (x.items || []).length + '</td><td class="ops">' + ops + '</td></tr>';
      }, '暂无待发药处方');
    document.getElementById('pending').onclick = function (e) {
      var b = e.target.closest('button'); if (!b || !b.getAttribute('data-disp')) return;
      POST('/api/prescriptions/' + b.getAttribute('data-disp') + '/transition', {action: 'to_dispensed'})
        .then(function () { toast('发药成功'); location.reload(); })
        .catch(function (e2) { toast(e2.message, true); });
    };
    document.getElementById('logs').innerHTML = table(
      ['时间', '药品', '~数量', '批次', '操作人'], rs[1].data.items, function (x) {
        return '<tr><td>' + esc(x.created_at) + '</td><td>' + esc(x.drug_name || '') + '</td>' +
          '<td class="num">' + x.qty + '</td><td>' + esc(x.batch_no || '—') + '</td>' +
          '<td>' + esc(x.operator || '—') + '</td></tr>';
      });
  });
};

/* ---------- 药品库存 ---------- */
PAGES.inventory = function (main) {
  main.innerHTML = '<h2>药品库存</h2><div class="toolbar">' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  if (document.getElementById('btn-export'))
    document.getElementById('btn-export').onclick = function () { dl('/api/export/inventory', 'inventory.csv'); };
  function load() {
    GET('/api/inventory').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['药品', '批次', '~数量', '效期', '~安全库存', '状态'], r.data.items, function (x) {
          var expSoon = x.expire_at && (new Date(x.expire_at) - new Date()) < 90 * 86400000;
          var low = x.qty <= x.safe_stock;
          return '<tr><td>' + esc(x.drug_name || x.drug_id) + '</td><td>' + esc(x.batch_no) + '</td>' +
            '<td class="num">' + x.qty + '</td><td>' + esc(x.expire_at || '—') + '</td>' +
            '<td class="num">' + x.safe_stock + '</td>' +
            '<td>' + (low ? tag('低库存', 'err') : (expSoon ? tag('临期', 'warn') : tag('正常', 'ok'))) + '</td></tr>';
        });
    });
  }
  load();
};

/* ---------- 供应商 ---------- */
PAGES.supplier = function (main) {
  main.innerHTML = '<h2>供应商管理</h2><div class="toolbar">' +
    (perm('his.suppliers.write') ? '<button class="btn" id="btn-new">新增供应商</button>' : '') +
    '</div><div id="list"></div>';
  function load() {
    GET('/api/suppliers').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['名称', '联系人', '电话', '~账期(天)', '~应付金额'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.name) + '</td><td>' + esc(x.contact || '—') + '</td>' +
            '<td>' + esc(x.phone || '—') + '</td><td class="num">' + x.credit_days + '</td>' +
            '<td class="num">' + fmtCents(x.payable_cents) + '</td></tr>';
        });
    });
  }
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      modal('<h3>新增供应商</h3>' +
        field('名称', '<input id="f-name">') +
        field('联系人', '<input id="f-contact">') +
        field('电话', '<input id="f-phone">') +
        field('账期(天)', '<input id="f-days" type="number" value="30">') +
        '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
        '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('btn-ok').onclick = function () {
        POST('/api/suppliers', {
          name: document.getElementById('f-name').value.trim(),
          contact: document.getElementById('f-contact').value.trim(),
          phone: document.getElementById('f-phone').value.trim(),
          credit_days: Number(document.getElementById('f-days').value)
        }).then(function () { toast('已保存'); closeModal(); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    };
  load();
};

/* ---------- 财务流水 ---------- */
PAGES.finance = function (main) {
  main.innerHTML = '<h2>财务流水</h2><div class="toolbar">' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="sum"></div><div id="list"></div>';
  document.getElementById('btn-export').onclick = function () { dl('/api/export/transactions', 'transactions.csv'); };
  Promise.all([GET('/api/finance/summary'), GET('/api/transactions')]).then(function (rs) {
    var s = rs[0].data, items = rs[1].data.items;
    document.getElementById('sum').innerHTML = '<div class="kpis">' +
      kpi(fmtCents(s.income_cents), '今日收入', 'ok') +
      kpi(fmtCents(s.refund_cents), '今日退款', 'err') +
      kpi(s.charge_count, '收费单') +
      kpi(s.rx_count, '处方单') + '</div>';
    var TT = {'income': ['收入', 'ok'], 'expense': ['采购', 'warn'], 'refund': ['退款', 'err']};
    document.getElementById('list').innerHTML = table(
      ['时间', '类型', '~金额', '方式', '备注'], items, function (x) {
        var t = TT[x.ttype] || [x.ttype, ''];
        return '<tr><td>' + esc(x.created_at) + '</td><td>' + tag(t[0], t[1]) + '</td>' +
          '<td class="num">' + fmtCents(x.amount_cents) + '</td><td>' + esc(x.pay_method || '—') + '</td>' +
          '<td>' + esc(x.note || '') + '</td></tr>';
      });
  });
};

/* ---------- 风险预警 ---------- */
PAGES.risk = function (main) {
  main.innerHTML = '<h2>风险预警</h2><div class="toolbar">' +
    (perm('his.risks.write') ? '<button class="btn" id="btn-scan">立即扫描</button>' : '') +
    '</div><div id="list"></div>';
  function load() {
    GET('/api/risks').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['类型', '标题', '详情', '~评分', '等级', '状态', '操作'], r.data.items, function (x) {
          var ops = '';
          if (perm('his.risks.write') && x.status === 'open')
            ops = '<button class="btn sm ghost" data-res="' + x.id + '">处理</button>';
          var rt = {'drug_low_stock': '药品低库存', 'drug_expiry': '效期预警', 'dose_over': '剂量超限',
                    'patient_overdue': '挂号超时'}[x.rtype] || x.rtype;
          return '<tr><td>' + esc(rt) + '</td><td>' + esc(x.title) + '</td><td>' + esc(x.detail || '') + '</td>' +
            '<td class="num">' + x.score + '</td><td>' + levelTag(x.grade) + '</td>' +
            '<td>' + tag(x.status === 'open' ? '未处理' : '已处理', x.status === 'open' ? 'err' : 'ok') + '</td>' +
            '<td class="ops">' + (ops || '—') + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b || !b.getAttribute('data-res')) return;
        PUT('/api/risks/' + b.getAttribute('data-res') + '/resolve', {note: '已人工处理'})
          .then(function () { toast('已处理'); load(); }).catch(function (e2) { toast(e2.message, true); });
      };
    });
  }
  if (document.getElementById('btn-scan'))
    document.getElementById('btn-scan').onclick = function () {
      POST('/api/risks/scan', {}).then(function (r) {
        toast('扫描完成，新增 ' + r.data.created + ' 条'); load();
      }).catch(function (e) { toast(e.message, true); });
    };
  load();
};

/* ---------- 系统管理 ---------- */
PAGES.system = function (main) {
  main.innerHTML = '<h2>系统管理</h2><div class="grid2">' +
    '<div class="card"><h3>用户</h3><div id="users">加载中…</div></div>' +
    '<div class="card"><h3>公告</h3><div id="notices">加载中…</div></div>' +
    (perm('*') ? '<div class="card"><h3>API Key（对接外部系统）</h3><div id="keys">加载中…</div></div>' +
      '<div class="card"><h3>增量同步状态</h3><div id="sync">加载中…</div></div>' : '') +
    '</div>';
  GET('/api/users').then(function (r) {
    document.getElementById('users').innerHTML = table(
      ['用户名', '姓名', '角色'], r.data.items, function (x) {
        return '<tr><td>' + esc(x.username) + '</td><td>' + esc(x.name || '') + '</td><td>' + esc(x.role) + '</td></tr>';
      });
  }).catch(function () { document.getElementById('users').innerHTML = '<div class="empty">无权限</div>'; });
  GET('/api/notices').then(function (r) {
    document.getElementById('notices').innerHTML = (r.data.items || []).map(function (n) {
      return '<p><b>' + esc(n.title) + '</b><br>' + esc(n.content || '') + '</p>';
    }).join('') || '<div class="empty">暂无</div>';
  });
  if (perm('*')) {
    GET('/api/api-keys').then(function (r) {
      document.getElementById('keys').innerHTML =
        '<div class="toolbar"><button class="btn sm" id="btn-key">生成 Key</button></div>' +
        table(['名称', '前缀', '权限', '最近使用'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.name) + '</td><td>' + esc(x.prefix || '') + '</td>' +
            '<td>' + esc(x.perms) + '</td><td>' + esc(x.last_used || '—') + '</td></tr>';
        });
      document.getElementById('btn-key').onclick = function () {
        POST('/api/api-keys', {name: '外部对接-' + Date.now() % 10000}).then(function (r2) {
          modal('<h3>API Key 已生成（仅显示一次）</h3><p class="key-line">' + esc(r2.data.key) + '</p>' +
            '<div class="m-foot"><button class="btn" onclick="closeModal()">我已保存</button></div>');
        });
      };
    });
    GET('/api/sync?since=0&entities=patients').then(function (r) {
      var d = r.data || {};
      document.getElementById('sync').innerHTML =
        '<p>同步版本：<b>' + (d.version || 0) + '</b>，本轮变更 <b>' + (d.changes || []).length + '</b> 条</p>' +
        '<p>支持实体：patients / doctors / registrations / prescriptions / charges / inventory / risks</p>';
    });
  }
};
