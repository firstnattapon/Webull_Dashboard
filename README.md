# Webull Dashboard

Streamlit dashboard สำหรับดู Shannon Demon state/trades และหน้า **Manual Test
Lab** สำหรับทดสอบ Webull, DNA, Logical FIX_C และ benchmark แบบเจาะจง

Manual Test Lab รองรับ connection/quote, account list, balance, positions,
order preview/place, open orders, history, detail, cancel, DNA encode/decode,
Logical FIX_C และ local benchmark

## Run locally

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m streamlit run streamlit_dashboard.py
```

หน้า Manual ใช้งานได้โดยไม่ต้องตั้งค่า Firestore ส่วนหน้า Dashboard ต้องมี
`.streamlit/secrets.toml` ที่ประกอบด้วย `firebase_service_account`

## Realized cash-flow contract

ตาราง trade log แยกข้อมูลสองชนิดออกจากกัน:

- กราฟ Learning Guide เป็น **what-if price path** จาก market quote
- คอลัมน์ `ΔAₙ`, `Aₙ` และ `Eₙ` เป็น **realized execution ledger** และรับข้อมูล
  เฉพาะ terminal fill ที่มี `filled_quantity > 0`, `position_reconciled = true`,
  side เป็น BUY/SELL และมี execution/average fill price จริง

`PASS`, pending, rejected, unfilled และ `ORDER_*_POSITION_PENDING` ไม่ทำให้ยอด
realized เปลี่ยน และ dashboard จะไม่ใช้ `last_price` แทน execution price หาก
trade document ยังไม่มีราคาที่ execute คอลัมน์ realized จะเว้นว่างพร้อมคำเตือน
เพื่อไม่สร้างตัวเลขเงินจริงที่พิสูจน์ไม่ได้ ค่า `Aₙ` จะหัก fee เมื่อ log มี field
ค่าธรรมเนียมที่รองรับ มิฉะนั้นจะแสดง gross cash พร้อม contract นี้อย่างชัดเจน

## Security

- ค่าเริ่มต้นของ Manual คือ **Test (UAT)**
- Account ID, App Key และ App Secret ต้องกรอกขณะใช้งานและไม่ถูกเขียนลงไฟล์
- ห้าม commit `.streamlit/secrets.toml`, `.env` หรือ credentials ใด ๆ
- Production order ต้องเปิด safety switch และพิมพ์ confirmation phrase ให้ตรง
- Credential ที่เคยส่งผ่านแชตหรือช่องทางสาธารณะควรถูก revoke/rotate

## Test

```bash
.venv/Scripts/python -m pytest -q
```
