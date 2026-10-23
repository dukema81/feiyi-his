# -*- coding: utf-8 -*-
"""飞医 HIS 演示数据 seed（幂等：仅空库写入）"""
import hashlib
from datetime import date, timedelta
import db

def hash_pwd(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def run():
    db.init_db()
    if db.q1("SELECT id FROM users LIMIT 1"):
        print("seed: not empty, skip")
        return
    db.init_db()
    today = date.today()

    users = [
        ("admin", "系统管理员", "admin", ""),
        ("lidw", "李大伟", "doctor", "13800000001"),
        ("zhangm", "张敏", "doctor", "13800000002"),
        ("wangn", "王楠", "nurse", "13800000003"),
        ("chenyf", "陈亚芳", "pharmacist", "13800000004"),
        ("liug", "刘刚", "cashier", "13800000005"),
        ("zhaock", "赵仓储", "warehouse", "13800000006"),
        ("reader01", "只读用户", "reader", ""),
    ]
    for u, name, role, phone in users:
        db.execute("INSERT INTO users(username,password,name,role,phone) VALUES(?,?,?,?,?)",
                   (u, hash_pwd("123456"), name, role, phone))

    depts = [("内科", "门诊楼2层201-206", "心血管/呼吸/消化"),
             ("外科", "门诊楼2层210-215", "普外/骨科"),
             ("儿科", "门诊楼3层301-305", "儿童保健"),
             ("检验科", "医技楼1层", "血常规/生化"),
             ("药剂科", "门诊楼1层", "药房/药库")]
    for name, loc, remark in depts:
        db.execute("INSERT INTO departments(name,location,remark) VALUES(?,?,?)", (name, loc, remark))

    doctors = [
        ("李大伟", 1, "主任医师", 3000, "心血管疾病"),
        ("张敏", 1, "副主任医师", 2500, "呼吸系统"),
        ("王强", 2, "主治医师", 1800, "普外科"),
        ("刘慧", 3, "副主任医师", 2200, "儿科常见病"),
        ("陈志", 2, "主任医师", 3500, "骨科"),
    ]
    for name, dept, title, fee, spec in doctors:
        db.execute("INSERT INTO doctors(name,dept_id,title,fee_cents,specialty) VALUES(?,?,?,?,?)",
                   (name, dept, title, fee, spec))

    patients = [
        ("P0001", "张三", "M", "1980-05-12", "13911112222", "青霉素过敏", "employee", "BJ2024EMP001"),
        ("P0002", "李四", "F", "1992-11-03", "13933334444", "", "resident", "BJ2024RES002"),
        ("P0003", "王五", "M", "1965-02-28", "13955556666", "磺胺类过敏", "employee", "BJ2024EMP003"),
        ("P0004", "赵六", "F", "2015-08-19", "13977778888", "", "self", ""),
        ("P0005", "钱七", "M", "1978-12-01", "13999990000", "", "resident", "BJ2024RES005"),
        ("P0006", "孙八", "F", "2001-04-15", "13912123434", "乳胶过敏", "self", ""),
    ]
    for mrn, name, gender, birth, phone, allergy, itype, ino in patients:
        db.execute("INSERT INTO patients(mrn,name,gender,birth,phone,allergy,insurance_type,insurance_no) VALUES(?,?,?,?,?,?,?,?)",
                   (mrn, name, gender, birth, phone, allergy, itype, ino))

    drugs = [
        ("阿莫西林胶囊", "0.25g×24粒", "盒", 1580, 0.5, 1, 20),
        ("布洛芬缓释胶囊", "0.3g×20粒", "盒", 2200, 0.6, 0, 15),
        ("氨氯地平片", "5mg×28片", "盒", 3200, 0.2, 1, 10),
        ("头孢克肟颗粒", "50mg×6袋", "盒", 2680, 0.1, 1, 12),
        ("蒙脱石散", "3g×10袋", "盒", 1900, 0.0, 0, 10),
        ("维生素C片", "0.1g×100片", "瓶", 900, 0.0, 0, 8),
    ]
    for name, spec, unit, price, maxdose, rx, safe in drugs:
        db.execute("INSERT INTO drugs(name,spec,unit,price_cents,max_dose,rx_required,safe_stock) VALUES(?,?,?,?,?,?,?)",
                   (name, spec, unit, price, maxdose, rx, safe))

    suppliers = [("国药控股北京分公司", "孙经理", "010-88886666", 30),
                 ("华北制药直销处", "马经理", "0311-66889900", 45)]
    for name, contact, phone, days in suppliers:
        db.execute("INSERT INTO suppliers(name,contact,phone,credit_days) VALUES(?,?,?,?)", (name, contact, phone, days))

    # 排班：未来 3 天，每医生上午/下午
    for d in range(1, 6):
        for offset in (0, 1, 2):
            db.execute("INSERT INTO schedules(doctor_id,sched_date,period,quota) VALUES(?,?,?,?)",
                       (d, (today + timedelta(days=offset)).isoformat(), "AM" if d % 2 else "PM", 20))

    # 库存批次：含低库存与临期样例
    invs = [
        (1, "B20260901", 50, (today + timedelta(days=300)).isoformat()),
        (2, "B20261010", 8, (today + timedelta(days=200)).isoformat()),      # 低库存 8≤15
        (3, "B20260815", 12, (today + timedelta(days=60)).isoformat()),      # 临期 60≤90
        (4, "B20261101", 30, (today + timedelta(days=360)).isoformat()),
        (5, "B20260920", 20, (today + timedelta(days=250)).isoformat()),
        (6, "B20270105", 5, (today + timedelta(days=400)).isoformat()),      # 低库存 5≤8
    ]
    for drug, batch, qty, exp in invs:
        db.execute("INSERT INTO inventory(drug_id,batch_no,qty,expire_at) VALUES(?,?,?,?)", (drug, batch, qty, exp))

    notices = [("系统上线公告", "飞医HIS v1.0 正式上线，请各科室及时熟悉系统。", "info"),
               ("药品调价通知", "氨氯地平片价格调整，请药房留意。", "warn")]
    for t, c, lv in notices:
        db.execute("INSERT INTO notices(title,content,level) VALUES(?,?,?)", (t, c, lv))

    # 演示就诊链路：挂号→叫号→完成→病历→处方→发药→收费
    sched = db.q1("SELECT * FROM schedules WHERE doctor_id=1 AND sched_date=? AND period='AM'", (today.isoformat(),))
    if sched:
        fee = db.q1("SELECT fee_cents FROM doctors WHERE id=1")["fee_cents"]
        c = db.execute("INSERT INTO registrations(no,patient_id,schedule_id,doctor_id,dept_id,fee_cents,status,no_in_queue) VALUES(?,?,?,?,?,?,?,?)",
                       ("GH" + today.strftime("%Y%m%d") + "-901", 2, sched["id"], 1, 1, fee, "done", 1))
        reg_id = c.lastrowid
        db.execute("UPDATE schedules SET booked=booked+1 WHERE id=?", (sched["id"],))
        db.execute("INSERT INTO clinic_records(registration_id,patient_id,doctor_id,chief_complaint,history,diagnosis,advice) VALUES(?,?,?,?,?,?,?)",
                   (reg_id, 2, 1, "咳嗽咳痰3天，伴低热", "既往体健，无药物过敏", "急性上呼吸道感染", "注意休息，多饮水，一周后复诊"))
        total = 2 * 1580 + 1900
        c = db.execute("INSERT INTO prescriptions(no,patient_id,doctor_id,registration_id,status,total_cents) VALUES(?,?,?,?,?,?)",
                       ("CF" + today.strftime("%Y%m%d") + "-901", 2, 1, reg_id, "dispensed", total))
        rx_id = c.lastrowid
        db.execute("INSERT INTO prescription_items(prescription_id,drug_id,drug_name,dose,frequency,days,qty,price_cents,amount_cents) VALUES(?,?,?,?,?,?,?,?,?)",
                   (rx_id, 1, "阿莫西林胶囊", 0.25, "tid", 3, 2, 1580, 3160))
        db.execute("INSERT INTO prescription_items(prescription_id,drug_id,drug_name,dose,frequency,days,qty,price_cents,amount_cents) VALUES(?,?,?,?,?,?,?,?,?)",
                   (rx_id, 5, "蒙脱石散", 3.0, "tid", 2, 1, 1900, 1900))
        db.execute("INSERT INTO pharmacy_logs(prescription_id,drug_id,drug_name,qty,batch_no,operator) VALUES(?,?,?,?,?,?)",
                   (rx_id, 1, "阿莫西林胶囊", 2, "B20260901", "陈亚芳"))
        db.execute("INSERT INTO pharmacy_logs(prescription_id,drug_id,drug_name,qty,batch_no,operator) VALUES(?,?,?,?,?,?)",
                   (rx_id, 5, "蒙脱石散", 1, "B20260920", "陈亚芳"))
        db.execute("UPDATE inventory SET qty=qty-2 WHERE drug_id=1 AND batch_no='B20260901'")
        db.execute("UPDATE inventory SET qty=qty-1 WHERE drug_id=5 AND batch_no='B20260920'")
        # 收费：李四 resident 0.65
        paid = int(total * 65 / 100)
        db.execute("INSERT INTO charges(no,patient_id,registration_id,prescription_ids,total_cents,discount_rate,paid_cents,pay_method,status) VALUES(?,?,?,?,?,?,?,?,?)",
                   ("SF" + today.strftime("%Y%m%d") + "-901", 2, reg_id, str(rx_id), total, 0.65, paid, "wechat", "paid"))
        db.execute("UPDATE registrations SET paid=1 WHERE id=?", (reg_id,))
        db.execute("INSERT INTO transactions(ttype,amount_cents,ref_type,ref_id,pay_method,note) VALUES('income',?, 'charge', 1, 'wechat', ?)",
                   (paid, "收费 SF" + today.strftime("%Y%m%d") + "-901"))
        # 第二条演示挂号：候诊中
        db.execute("INSERT INTO registrations(no,patient_id,schedule_id,doctor_id,dept_id,fee_cents,status,no_in_queue) VALUES(?,?,?,?,?,?,?,?)",
                   ("GH" + today.strftime("%Y%m%d") + "-902", 1, sched["id"], 1, 1, fee, "waiting", 2))
        db.execute("UPDATE schedules SET booked=booked+1 WHERE id=?", (sched["id"],))

    db.execute("INSERT OR REPLACE INTO his_rules(name,value) VALUES('insurance_rates','{\"employee\":0.85,\"resident\":0.65,\"self\":1.0}')")
    db.execute("INSERT OR REPLACE INTO his_rules(name,value) VALUES('expiry_warn_days','90')")
    # 显式初始化 seq（避免演示单号与 next_seq 冲突）
    db.execute("INSERT OR REPLACE INTO seq(name,val) VALUES('mrn',6)")
    db.execute("INSERT OR REPLACE INTO seq(name,val) VALUES('registration_no',0)")
    db.execute("INSERT OR REPLACE INTO seq(name,val) VALUES('prescription_no',0)")
    db.execute("INSERT OR REPLACE INTO seq(name,val) VALUES('charge_no',0)")
    db.execute("INSERT OR REPLACE INTO seq(name,val) VALUES('purchase_no',0)")
    print("seed: done (8 users, 5 depts, 5 doctors, 6 patients, 6 drugs, 5 schedules*3d, 6 batches)")

if __name__ == "__main__":
    run()
