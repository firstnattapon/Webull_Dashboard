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
