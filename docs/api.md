# 飞医医疗管理系统（HIS）API 接口契约

Base URL：`http://<host>/his/api`（生产经 nginx，本地直连 8028 端口根路径 `/api`）
版本：v1.0

## 1. 通用约定

### 1.1 响应包
所有接口返回统一 JSON：
```json
{"code": 200, "message": "ok", "data": { ... }}
```
`code` 与 HTTP 状态码一致：200 成功、400 参数错、401 未认证、403 无权限、404 不存在、409 冲突、422 业务规则拒绝、423 幂等冲突、500 服务器错误、501 未实现（预留接口）。

### 1.2 列表响应
```json
{"code":200,"message":"ok","data":{"items":[...],"total":57,"page":1,"size":20}}
```
通用查询参数：`page`(默认1)、`size`(默认20, ≤200)、`keyword`、`sort`、`order`、`store_id`→`dept_id` 等业务过滤。

### 1.3 鉴权（五通道，任选其一）
| 通道 | 示例 |
|---|---|
| Bearer | `Authorization: Bearer <token>` |
| 头 | `X-Token: <token>` |
| Cookie | `Cookie: his_token=<token>` 或 `token=<token>` |
| 查询 | `?token=<token>` |
| ApiKey | `X-Api-Key: <key>`（服务器存 SHA-256，默认 perms `his.*`） |

Token 登录签发，7 天有效。无凭证访问需鉴权接口返回 401。

### 1.4 幂等
写接口（POST/PUT/DELETE）支持请求头 `Idempotency-Key: <uuid>`；同一 key 重复请求返回首次结果（idem_keys 表）。

### 1.5 增量同步（供外部系统对接）
```
GET /api/sync?since=<version>&entities=patients,registrations,prescriptions
→ {"code":200,"data":{"version":123,"changes":[{"entity":"patients","op":"upsert","row":{...}}, ...]}}
```
`since=0` 为全量快照；省略 `entities` 返回全部实体。

### 1.6 导出
`GET /api/export/<entity>?format=csv` → `text/csv`（UTF-8 BOM）。支持 patients/registrations/prescriptions/charges/inventory/transactions。

## 2. 认证与系统

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/login | `{username,password}` → `{token,user}` |
| POST | /api/logout | 注销当前 token |
| GET | /api/me | 当前用户信息+权限 |
| GET | /api/health | 健康检查（免鉴权）`{"status":"ok"}` |
| GET | /api/notices | 公告列表 |
| POST | /api/notices | 新建公告（admin） |
| GET | /api/logs | 审计日志（admin） |
| GET/PUT | /api/rules | 业务参数（医保折扣率等） |

## 3. 基础主数据

### 3.1 科室 /api/departments
- `GET /` 列表；`POST /` 新建 `{name, location, remark}`
- `GET|PUT|DELETE /{id}`

### 3.2 医生 /api/doctors
- `GET /?dept_id=&title=&keyword=`；`POST /` `{name, dept_id, title, fee_cents, max_dose_note}`
- `GET|PUT|DELETE /{id}`

### 3.3 患者 /api/patients
- `GET /?keyword=&gender=`（按姓名/档案号/手机号模糊）；`POST /` `{name, gender, birth, phone, allergy, insurance_no}`
- `GET|PUT|DELETE /{id}`；`GET /{id}/visits` 就诊史（挂号+病历聚合）

### 3.4 药品 /api/drugs
- `GET /?keyword=&rx_required=`；`POST /` `{name, spec, unit, price_cents, max_dose, rx_required, safe_stock}`
- `GET|PUT|DELETE /{id}`

### 3.5 供应商 /api/suppliers
- `GET /?keyword=`；`POST /` `{name, contact, phone, credit_days}`
- `GET|PUT|DELETE /{id}`；余额见 `payable_cents`（来自采购应付流水）

## 4. 排班与挂号

### 4.1 排班 /api/schedules
- `GET /?doctor_id=&date_from=&date_to=`
- `POST /` `{doctor_id, sched_date, period(AM|PM), quota}` —— 同医生同时段重复返回 422
- `PUT /{id}` 修改（换医生/时段同样做冲突检测）；`DELETE /{id}`（已有挂号返回 409）

### 4.2 挂号 /api/registrations
- `GET /?patient_id=&doctor_id=&status=&date=`
- `POST /` `{patient_id, schedule_id}` → 生成 `GHyyyymmdd-xxx` 号，`fee_cents` 取医生挂号费，状态 waiting，占用排班余号（无余号 422）
- 状态流转 `POST /{id}/transition {to}`：
  - `waiting→called`（叫号）、`called→in_consult`（接诊，需先有病历可后补）、`in_consult→done`
  - `waiting|called→cancelled`（退号，释放余号）
  - 非法流转 422，body 含 `allowed: [...]`
- `GET /queue?schedule_id=` 候诊队列（waiting/called 按 no 升序）

## 5. 病历与处方

### 5.1 门诊病历 /api/clinic-records
- `POST /` `{registration_id, chief_complaint, history, diagnosis, advice}` —— 一挂号单一病历，重复返回 409
- `GET /?patient_id=&doctor_id=`；`GET|PUT /{id}`

### 5.2 处方 /api/prescriptions
- `POST /` `{patient_id, doctor_id, registration_id?, items:[{drug_id, dose, frequency, days, qty}]}` → `CFyyyymmdd-xxx`，金额 Decimal 累计 `total_cents`；剂量超 `drugs.max_dose` 不阻断但生成 dose_over 风险
- 状态流转 `POST /{id}/transition {to}`：`draft→submitted`（校验库存可满足）、`submitted→dispensed`（发药扣库存，见药房）、`draft|submitted→cancelled`
- `GET /?patient_id=&status=&date_from=`；`GET /{id}`（含 items 明细）

## 6. 收费

### 6.1 收费单 /api/charges
- `POST /` `{registration_id?, prescription_ids?:[], pay_method:cash|wechat|alipay|insurance, received_cents}` —— 汇总挂号费+处方费，按患者医保类型（insurance_type: employee→0.85 / resident→0.65 / self→1.00）计折，`paid_cents = total_cents × rate` Decimal HALF_UP 到分；生成收入流水；挂号单需处于 done 或一并流转
- `GET /?patient_id=&pay_method=&date_from=`；`GET /{id}`（含 charge_items 明细）
- `POST /{id}/refund` 退费 → 负流水，单据状态 refunded

### 6.2 流水 /api/transactions
- `GET /?type=income|expense|refund&date_from=&date_to=`
- `GET /api/finance/summary?date=` → `{income_cents, refund_cents, by_method:{...}, charge_count, rx_count}`

## 7. 药房与库存

### 7.1 发药
处方 `submitted→dispensed` 即发药：按 inventory 批次 **效期近先出（FEFO）** 扣减；任一药品不足整体失败 422（事务回滚），成功写 pharmacy_logs。

- `GET /api/pharmacy/logs?date=&drug_id=`；`GET /api/pharmacy/pending` 待发处方列表

### 7.2 药品库存 /api/inventory
- `GET /?drug_id=&keyword=&near_expiry_days=`（默认按效期升序）
- 只读：入库唯一通道为采购 receive；`GET /api/inventory/summary?drug_id=` 汇总可用量

### 7.3 采购 /api/purchases
- `GET /?status=&supplier_id=`；`POST /` `{supplier_id, items:[{drug_id, qty, cost_cents, batch_no, expiry}]}` → `CGyyyymmdd-xxx`
- 状态流转 `POST /{id}/transition {to}`：`draft→submitted`、`submitted→received`（入批次库存 + 应付流水，`received_cents = Σ qty×cost_cents` 供应商余额累加）
- `draft→cancelled`

## 8. 风险中心

- `POST /api/risk/scan` → 执行五类扫描，返回 `{created, by_type:{...}}`
- `GET /api/risk?status=&level=&type=`；`POST /api/risk/{id}/resolve {note}` 关闭风险

## 9. 用户与系统管理（admin）

- `GET|POST /api/users`，`PUT|DELETE /api/users/{id}`（不改密码字段时忽略；`PUT /api/users/{id}/password {password}` 改密）
- `GET|POST /api/api-keys`，`DELETE /api/api-keys/{id}` —— 返回明文仅一次
- `GET /api/dashboard` → 今日挂号/接诊/处方/收费金额、待发药、低库存数、临期数、候诊队列长度
- `GET /api/sync?since=&entities=`（见 1.5）

## 10. 错误码示例

```json
// 422 排班冲突
{"code":422,"message":"该医生在该时段已有排班","data":{"allowed":[]}}
// 422 余号不足
{"code":422,"message":"排班余号不足","data":{}}
// 422 库存不足
{"code":422,"message":"库存不足: 阿莫西林胶囊","data":{"drug":"阿莫西林胶囊","need":10,"have":6}}
// 401 / 403
{"code":401,"message":"unauthorized","data":{}}
{"code":403,"message":"permission denied: his.charges.create","data":{}}
```

## 11. 角色权限矩阵（默认）

| 角色 | perms |
|---|---|
| admin | `*` |
| doctor | `his.patients.* his.clinic.* his.prescriptions.* his.registrations.read` |
| nurse | `his.registrations.* his.patients.read his.queue.*` |
| pharmacist | `his.pharmacy.* his.inventory.read his.prescriptions.read` |
| cashier | `his.charges.* his.patients.read his.transactions.read` |
| warehouse | `his.purchases.* his.inventory.* his.suppliers.* his.drugs.read` |
| reader | `his.*.read`（各域只读） |

写权限包含读权限；`*` 为超管。
