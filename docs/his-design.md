# 飞医医疗管理系统（HIS）建设方案

版本：v1.0 ｜ 密级：内部

## 1. 项目概述

飞医医疗管理系统（FeiYi HIS）面向中小型门诊/诊所/体检机构，提供患者管理、医生排班、门诊挂号、电子病历、处方开具、收费结算、药房发药、药品库存等一体化业务能力，并预留标准化 API 供第三方系统（医保、检验 LIS、影像 PACS、企业 OA/ERP 等）对接。

### 1.1 设计目标
- **零依赖部署**：Python 标准库 + SQLite（WAL），单机即可运行，无第三方包。
- **对外友好**：统一 REST 风格、统一响应包、Bearer/ApiKey/Cookie 五通道鉴权、幂等键、增量同步。
- **金额精确**：所有金额以「分」（cents）为单位，Decimal HALF_UP，杜绝浮点误差。
- **风控前置**：药品低库存、效期临期、处方剂量异常自动扫描告警。

### 1.2 与飞运/飞餐体系的关系
沿用集团「飞」系列管理系统架构范式（飞育/飞运/飞餐），端口 8028、路由前缀 `/his/`，与 nginx 网关统一托管。

## 2. 总体架构

```
浏览器 SPA (原生JS)
    │ /his/
nginx (80) ── proxy_pass http://127.0.0.1:8028/ (剥前缀)
    │
ThreadingHTTPServer (8028)
    ├── server.py  路由层（~80 路由）
    ├── his.py     纯函数业务内核（无IO可单测）
    ├── seed.py    演示数据
    └── db.py      sqlite3 WAL + execute 重试/回滚
            └── feiyi.db（24+ 表）
```

分层职责：
- **路由层**：鉴权、参数校验、调用内核、统一响应包 `{code, message, data}`。
- **业务内核**：挂号费计算、处方金额、医保折扣、排班冲突、剂量校验、库存扣减、风险扫描——纯函数，可独立单测。
- **数据层**：`execute()` 带 30 次锁重试，统一捕获 `OperationalError`/`IntegrityError` 并回滚。

## 3. 业务域设计

### 3.1 基础主数据
| 域 | 表 | 说明 |
|---|---|---|
| 科室 | departments | 内科/外科/儿科等，含诊室位置 |
| 医生 | doctors | 职称（主任医师/副主任医师/主治/住院）、挂号费、所属科室 |
| 患者 | patients | 档案号、性别、出生日期、过敏史、医保号 |
| 药品 | drugs | 规格、单位、零售价（分）、是否处方药 |
| 供应商 | suppliers | 资质、应付余额、账期 |

### 3.2 门诊业务
- **排班 schedules**：医生×日期×时段（上午/下午），冲突检测（同医生同时段不可重复排班）。
- **挂号 registrations**：选择排班→生成挂号号（GH+日期+序号）→收取挂号费→进入候诊队列；支持叫号（waiting→called→in_consult→done/cancelled）。
- **门诊病历 clinic_records**：主诉、现病史、诊断（ICD-10 可扩展）、处理意见；一挂号单可对应一条病历。
- **处方 prescriptions + prescription_items**：药品、剂量、用法、天数；金额 Decimal 累计到分；剂量校验（超阈值告警）。状态：draft→submitted→dispensed，可 cancelled（仅 draft/submitted）。

### 3.3 收费与医保
- **收费 charges**：挂号费 + 处方药品费合并应收；会员/医保折扣（职工 0.85、居民 0.65、自费 1.00，比例可配置）；实付、找零、支付方式（cash/wechat/alipay/insurance）；收入流水 transactions。
- 退费走负流水，保留完整轨迹。

### 3.4 药房与库存
- **发药 pharmacy**：处方 submitted→dispensed 时按批次 FIFO 扣减库存，生成发药记录；库存不足拒绝发药（422）。
- **药品库存 inventory**：批次号、效期、数量；入库仅经采购单 receive 通道。
- **采购 purchases + purchase_items**：draft→submitted→received；receive 时入批次库存并生成应付流水。

### 3.5 住院与体检（预留）
- 住院 admissions：床位、住院天数、押金（本期预留表结构，接口返回 501 Not Implemented）。
- 体检 checkups：套餐、项目（本期预留）。

### 3.6 风险中心 risks
| 类型 | 规则 | 等级 |
|---|---|---|
| drug_low_stock | 库存 ≤ 安全库存 | 30 warn |
| drug_expiry | 效期 ≤ 90 天 | 25 warn |
| dose_over | 单次剂量 > 药品 max_dose | 35 warn |
| doctor_conflict | 排班重叠 | 20 risk |
| patient_overdue | 挂号 24h 未就诊未退号 | 20 risk |

### 3.7 平台域
users/tokens/api_keys/notices/logs/idem_keys/sync_state/his_rules/seq，与飞餐同构：角色 admin/doctor/nurse/pharmacist/cashier/warehouse/reader，权限通配 `*`、前缀 `his.*`、写含读。

## 4. 数据模型（24+ 表）

patients, doctors, departments, schedules, registrations, clinic_records, prescriptions, prescription_items, charges, charge_items, pharmacy_logs, drugs, inventory, purchases, purchase_items, suppliers, transactions, risks, users, tokens, api_keys, notices, logs, idem_keys, sync_state, his_rules, seq（27 表）

关键约束：
- 单号统一 `seq` 表发号（GH 挂号、CF 处方、CG 收费、CG 采购）。
- `inventory(drug_id, batch_no)` 唯一；`schedules(doctor_id, sched_date, period)` 唯一。
- 金额字段一律 `*_cents`（INTEGER）。

## 5. 安全与鉴权

- 密码 SHA-256(salt+pwd) 存储；登录签发 token（tokens 表，7 天过期）。
- 五通道鉴权：`Authorization: Bearer` / `X-Token` / `Cookie(his_token|token)` / `?token=` / `X-Api-Key`（SHA-256 存储，默认 perms `his.*`）。
- 幂等：`Idempotency-Key` 头 → idem_keys，写接口重复请求返回首次结果。
- 全量审计 logs 表（user/action/detail/ip）。

## 6. 非功能要求

- 性能：SQLite WAL 并发读写，接口 P95 < 100ms（单机百人门诊规模）。
- 可用性：systemd 守护 + nginx 反代；数据文件日备。
- 可扩展：医保/LIS 对接仅需按 `docs/api.md` 契约调用，Token/ApiKey 均支持。

## 7. 交付物

| 交付物 | 位置 |
|---|---|
| 设计/API/测试/操作手册（md + docx） | docs/ |
| DEMO 单文件 HTML（zip） | demo/ |
| 后端 + 前端 + 测试 | backend/ frontend/ tests/ |
| 部署 | systemd feiyi-his (8028) + nginx /his/ |
| 源码 | github.com/dukema81/feiyi-his |
