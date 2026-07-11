"""Read-only Shannon Demon Firestore dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account

from manual_tools import (
    rebalancing_cashflow_from_prices,
    rebalancing_reference_curve,
)
from rebalancing_charts import cashflow_comparison_chart, reference_shift_chart
from trade_log import (
    TRADE_PRICE_COLUMNS,
    build_trade_log_display,
    find_trade_price_column,
    trade_price_series,
)

st.set_page_config(page_title="Shannon Demon Dashboard", layout="wide")


@st.cache_resource
def get_client(project_id: str) -> firestore.Client:
    info = dict(st.secrets["firebase_service_account"])
    creds = service_account.Credentials.from_service_account_info(info)
    return firestore.Client(credentials=creds, project=project_id)


def load_state(db: firestore.Client, collection: str, document: str) -> dict:
    snapshot = db.collection(collection).document(document).get()
    return snapshot.to_dict() or {}


def load_trades(db: firestore.Client, collection: str, limit: int) -> pd.DataFrame:
    docs = (
        db.collection(collection)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    rows = [doc.to_dict() for doc in docs]
    return pd.json_normalize(rows, sep="_") if rows else pd.DataFrame()


def render_reference_chart(fix_c: float, p0: float, excess: float) -> None:
    st.markdown("#### กราฟที่ 2 — เงินทุนเทียบกับระดับราคา")
    st.code(
        "แกน X: ราคา x ตั้งแต่ 0 ถึง 2t₀\n"
        "Y₁(x) = Fix_c × ln(x / t₀)   ← เส้นอ้างอิง\n"
        "Y₂(x) = Y₁(x) + Eₙ           ← เส้นอ้างอิง + เงินเกินทุนสะสม",
        language=None,
    )
    curve_rows = rebalancing_reference_curve(fix_c, p0, excess, points=300)
    st.altair_chart(reference_shift_chart(curve_rows, p0), use_container_width=True)
    st.caption(
        "แกนราคาเริ่มแสดงที่ 0 แต่ไม่ลากเส้นที่ x = 0 เพราะ ln(0) มุ่งสู่ −∞; "
        "Y₂ คือ Y₁ ที่เลื่อนขึ้นในแนวตั้งเท่ากับ Eₙ ช่องว่างระหว่างเส้นจึงคงที่ "
        "ค่าบวกคือเงินสดที่ได้รับจากการขาย ค่าลบคือเงินสดที่ใช้ซื้อ"
    )


with st.sidebar:
    st.header("Firestore target")
    try:
        default_project = dict(st.secrets["firebase_service_account"]).get(
            "project_id", ""
        )
    except (KeyError, FileNotFoundError):
        default_project = ""
    project_id = st.text_input("Project ID", value=default_project)
    state_collection = st.text_input(
        "State collection", value="shannon_demon_state"
    )
    state_document = st.text_input(
        "State document", value="SHANNON_DEMON_DNA_SMR"
    )
    trade_collection = st.text_input(
        "Trade collection", value="shannon_demon_trades"
    )
    trade_limit = st.number_input(
        "Trades to show", min_value=10, max_value=1000, value=100, step=10
    )
    st.divider()
    st.header("Rebalancing guide")
    guide_fix_c = st.number_input(
        "Fix_c", min_value=0.01, value=1500.0, step=100.0, format="%.2f"
    )
    guide_p0 = st.number_input(
        "ราคาเริ่มต้น t₀ (P₀)",
        min_value=0.01,
        value=100.0,
        format="%.5f",
        help=(
            "ใช้เฉพาะเส้นสาธิตตอนยังไม่มี trade log — เมื่อมีข้อมูลแล้ว "
            "ระบบ anchor P₀ ที่ราคาแรกในหน้าต่างโดยอัตโนมัติ "
            "เพื่อไม่ให้เกิดสเต็ปปลอมจาก P₀ ที่ไกลจากราคาจริง"
        ),
    )
    if st.button("Refresh"):
        st.cache_resource.clear()
        st.rerun()

st.title("Shannon Demon Dashboard")
st.page_link("pages/Manual.py", label="Open Manual Test Lab", icon="🧪")

st.subheader("หลักการ Rebalancing Learning Guide 101")
principle_cols = st.columns(3)
with principle_cols[0]:
    st.markdown("#### 1) เส้นอ้างอิง Rₙ — ทุน×เทรนด์")
    st.code("Rₙ = Fix_c × ln(Pₙ / P₀)", language=None)
    st.caption(
        "กระแสเงินสด baseline ที่ระดับราคาอย่างเดียวอธิบายได้ "
        "(rebalance ต่อเนื่องเชิงอุดมคติ) — ขึ้นลงตามเทรนด์ ไม่ใช่ฝีมือ harvest"
    )
with principle_cols[1]:
    st.markdown("#### 2) เงินสดสะสมจริง Aₙ")
    st.code("Aₙ = Fix_c × Σ [Pᵢ / Pᵢ₋₁ − 1]", language=None)
    st.caption(
        "กระแสเงินสดสุทธิจากการ rebalance ทุกสเต็ป (+ รับจากขาย, − จ่ายซื้อ) "
        "— ยังปนส่วนของเทรนด์ จึงไม่ใช่ตัววัดกำไรโดยตรง"
    )
with principle_cols[2]:
    st.markdown("#### 3) กำไร harvest จริง Eₙ")
    st.code("Eₙ = Aₙ − Rₙ  ≥ 0", language=None)
    st.caption(
        "ทุนส่วนเกินเหนือเส้นอ้างอิง = กำไรจากความผันผวนล้วน ๆ "
        "(แยกทุนและเทรนด์ออกแล้ว) ไม่ลดลงเลย และ realize เต็ม"
        "เมื่อรอบซื้อ-ขายปิด (ราคาย้อนกลับมาระดับเดิม)"
    )

if not project_id:
    st.info("ตั้งค่า firebase_service_account และ Project ID เพื่ออ่าน Firestore")
    render_reference_chart(float(guide_fix_c), float(guide_p0), 0.0)
    st.stop()

try:
    db = get_client(project_id)
    state = load_state(db, state_collection, state_document)
    if state:
        cols = st.columns(4)
        cols[0].metric("DNA step", state.get("dna_step", "-"))
        cols[1].metric("Last signal", state.get("last_signal", "-"))
        cols[2].metric("Last status", state.get("last_status", "-"))
        last_logged = state.get("last_logged_at")
        cols[3].metric("Last logged at", str(last_logged) if last_logged else "-")
    else:
        st.info(f"ยังไม่มี state document ที่ {state_collection}/{state_document}")

    st.subheader("Trade log")
    trades = load_trades(db, trade_collection, int(trade_limit))
    if trades.empty:
        st.info(f"ยังไม่มี trade log ใน collection {trade_collection}")
        render_reference_chart(float(guide_fix_c), float(guide_p0), 0.0)
    else:
        if "status" in trades:
            st.bar_chart(trades["status"].value_counts())

        price_column = find_trade_price_column(trades)
        prices = (
            trade_price_series(trades, price_column) if price_column else []
        )
        # Anchor P₀ at the first price inside the window so Aₙ/Rₙ/Eₙ all
        # start at 0 (ทุนถูกแยกออก) and measure only what happened in view.
        # An external P₀ far from the traded range would inject one huge
        # synthetic first step that dwarfs the real harvest.
        anchor_p0 = prices[0] if prices else float(guide_p0)

        if price_column:
            st.caption(
                "จัดกลุ่มคอลัมน์เพื่ออ่านง่าย — "
                "① Logged DNA (บันทึกจากบอท) · "
                "② เส้นอ้างอิงทางทฤษฎี Rₙ · "
                "③ เส้น Rebalancing จริง Aₙ, Eₙ "
                f"(คอลัมน์ราคา: `{price_column}` · "
                f"anchor P₀ = ราคาแรกในหน้าต่าง {anchor_p0:,.2f} "
                "→ แถวเก่าสุด Aₙ = Rₙ = Eₙ = 0)"
            )
            st.caption(
                "เครื่องหมาย ส่วนต่างเป้าหมาย: − ต้องขายออก · + ต้องซื้อเข้า "
                "(มุมปรับพอร์ต — ตรงข้ามกับ ΔAₙ/Aₙ ที่ + คือเงินสดรับจากการขาย)"
            )
            st.dataframe(
                build_trade_log_display(
                    trades, price_column, float(guide_fix_c), anchor_p0
                ),
                use_container_width=True,
            )
        else:
            st.dataframe(trades, use_container_width=True)

        st.subheader("กราฟตาม Learning Guide 101 จาก trade log")
        if not prices:
            st.info(
                "ไม่พบคอลัมน์ราคาที่ใช้งานได้ใน trade log "
                f"(มองหา: {', '.join(TRADE_PRICE_COLUMNS)} "
                "รวมถึงคอลัมน์จากข้อมูลซ้อนที่ลงท้ายด้วยชื่อเหล่านี้) "
                "จึงแสดงเฉพาะเส้นอ้างอิงทางทฤษฎี"
            )
            render_reference_chart(float(guide_fix_c), float(guide_p0), 0.0)
        else:
            rows = rebalancing_cashflow_from_prices(
                prices, float(guide_fix_c), anchor_p0
            )
            final_row = rows[-1]
            actions = trades.get("decision_action")
            real_trades = (
                int(actions.isin(["BUY", "SELL"]).sum())
                if actions is not None
                else 0
            )
            cols = st.columns(5)
            cols[0].metric(
                "กำไร harvest Eₙ", f"{final_row['excess']:+,.2f}"
            )
            cols[1].metric("ราคาสุดท้าย Pₙ", f"{final_row['price']:,.2f}")
            cols[2].metric(
                "เงินสดสะสม Aₙ", f"{final_row['actual_cumulative']:+,.2f}"
            )
            cols[3].metric("อ้างอิง Rₙ", f"{final_row['ln_reference']:+,.2f}")
            cols[4].metric("เทรดจริง (BUY/SELL)", real_trades)
            if real_trades == 0:
                st.warning(
                    "ทุกแถวในหน้าต่างนี้เป็น PASS — ไม่มีการส่ง order จริง "
                    "Aₙ/Rₙ/Eₙ ที่แสดงจึงเป็นเส้นเชิงทฤษฎีจาก price path "
                    "(what-if rebalance ทุก tick) ไม่ใช่เงินสดที่ทำได้จริง"
                )
            st.caption(
                f"anchor P₀ = ราคาแรกในหน้าต่าง ({anchor_p0:,.2f}) → "
                "Eₙ เริ่มจาก 0 แยกทุนออก อ่านเป็นกำไรสะสมได้ตรง ๆ; "
                "เส้น Rₙ เต็มประวัติตั้งแต่ P₀ จริงของบอทดูได้จากคอลัมน์ "
                "`baseline_pnl` ที่บอทบันทึกไว้ทุกแถว"
            )

            st.markdown(
                f"#### กราฟที่ 1 — เปรียบเทียบตามลำดับ trade (คอลัมน์ราคา: "
                f"`{price_column}`)"
            )
            st.altair_chart(
                cashflow_comparison_chart(rows, x_title="ลำดับ trade"),
                use_container_width=True,
            )
            render_reference_chart(
                float(guide_fix_c), anchor_p0, float(final_row["excess"])
            )
except Exception as exc:
    st.error(f"Firestore error: {exc}")
