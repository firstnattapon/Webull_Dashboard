from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st
from google.cloud.firestore_v1 import Query

# Firebase Admin SDK is the easiest way to authenticate with Firestore on Streamlit Cloud.
import firebase_admin
from firebase_admin import credentials, firestore


# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Webull Bot Dashboard",
    page_icon="📈",
    layout="wide",
)


# =========================
# Firestore connection
# =========================
@st.cache_resource(show_spinner=False)
def init_firestore():
    """
    Initialize Firestore client.

    Streamlit Cloud:
      Put your service account JSON into st.secrets under:
      [firebase_service_account]

    Local development option:
      You can also use Google ADC by setting GOOGLE_APPLICATION_CREDENTIALS,
      but Streamlit Cloud should use st.secrets.
    """
    if firebase_admin._apps:
        return firestore.client()

    if "firebase_service_account" in st.secrets:
        service_account_info = dict(st.secrets["firebase_service_account"])

        # Streamlit TOML often stores private_key with escaped \n.
        # Firebase needs real newline characters.
        if "private_key" in service_account_info:
            service_account_info["private_key"] = service_account_info["private_key"].replace(
                "\\n", "\n"
            )

        cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(cred)
    else:
        # Fallback for local environment using Application Default Credentials.
        firebase_admin.initialize_app()

    return firestore.client()


def to_json_safe(value: Any) -> Any:
    """Convert Firestore / nested values to JSON-friendly values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, dict):
        return {k: to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_json_safe(v) for v in value]
    return value


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Flatten fields commonly used by the bot so the table is easier to read.
    Keeps raw nested fields too when useful.
    """
    row = dict(record)

    market_state = record.get("market_state") or {}
    decision = record.get("decision") or {}
    order_result = record.get("order_result") or {}

    if isinstance(market_state, dict):
        row["quantity"] = market_state.get("quantity")
        row["last_price"] = market_state.get("last_price")

    if isinstance(decision, dict):
        row["action"] = row.get("action") or decision.get("action")
        row["side"] = decision.get("side")
        row["order_quantity"] = decision.get("order_quantity")
        row["rebalance_amount"] = decision.get("rebalance_amount")
        row["value_now"] = decision.get("value_now")

    if isinstance(order_result, dict):
        row["order_id"] = order_result.get("order_id")
        row["order_status"] = order_result.get("status")
        row["client_order_id"] = row.get("client_order_id") or order_result.get(
            "client_order_id"
        )

    # Convert nested dictionaries to JSON strings for display/export.
    for key in ["market_state", "decision", "order_result"]:
        if isinstance(row.get(key), dict):
            row[key] = json.dumps(to_json_safe(row[key]), ensure_ascii=False)

    return row


def read_trade_logs(
    collection_name: str,
    limit: int,
    selected_statuses: list[str] | None = None,
) -> pd.DataFrame:
    db = init_firestore()

    query = (
        db.collection(collection_name)
        .order_by("created_at", direction=Query.DESCENDING)
        .limit(limit)
    )

    docs = query.stream()

    rows: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        data = to_json_safe(data)
        data["document_id"] = doc.id

        if selected_statuses and data.get("status") not in selected_statuses:
            continue

        rows.append(flatten_record(data))

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Parse created_at for sorting/charting.
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
        df = df.sort_values("created_at", ascending=False)

    return df


def read_state(state_collection: str = "shannon_demon_state") -> pd.DataFrame:
    db = init_firestore()

    rows: list[dict[str, Any]] = []
    for doc in db.collection(state_collection).stream():
        data = to_json_safe(doc.to_dict() or {})
        data["document_id"] = doc.id
        rows.append(data)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def metric_value(df: pd.DataFrame, column: str, default: str = "-") -> str:
    if df.empty or column not in df.columns:
        return default
    val = df.iloc[0].get(column)
    if pd.isna(val):
        return default
    return str(val)


# =========================
# Sidebar
# =========================
st.sidebar.title("⚙️ Settings")

collection_name = st.sidebar.text_input("Trade log collection", "trade_logs")
state_collection_name = st.sidebar.text_input("State collection", "shannon_demon_state")

limit = st.sidebar.slider("จำนวน log ล่าสุด", min_value=10, max_value=1000, value=100, step=10)

auto_refresh = st.sidebar.toggle("Auto refresh", value=False)
refresh_seconds = st.sidebar.selectbox("Refresh ทุกกี่วินาที", [10, 30, 60, 120], index=2)

if auto_refresh:
    # Streamlit built-in rerun loop without extra dependency.
    import time

    time.sleep(refresh_seconds)
    st.rerun()

st.sidebar.caption("Project: webull-bot-uat")
st.sidebar.caption("Collection หลัก: trade_logs")


# =========================
# Main
# =========================
st.title("📈 Webull Bot Dashboard")
st.caption("Dashboard สำหรับดู Firestore trade_logs ของ Cloud Function rebalance-trigger")

tabs = st.tabs(["📋 Trade Logs", "🧬 Bot State", "📊 Analytics", "🛠️ Debug"])

with tabs[0]:
    st.subheader("📋 Trade Logs")

    # First read without status filter to discover statuses.
    df_all = read_trade_logs(collection_name=collection_name, limit=limit)

    if df_all.empty:
        st.warning(
            "ยังไม่มีข้อมูลใน collection นี้ หรือ Streamlit ยังอ่าน Firestore ไม่ได้"
        )
        st.info(
            "ลองเรียก Cloud Function ด้วย curl หรือรอ Cloud Scheduler รอบถัดไป แล้วกด Refresh"
        )
    else:
        statuses = sorted([str(x) for x in df_all["status"].dropna().unique()]) if "status" in df_all.columns else []
        selected_statuses = st.multiselect(
            "กรอง status",
            statuses,
            default=statuses,
        )

        df = df_all
        if selected_statuses and "status" in df.columns:
            df = df[df["status"].isin(selected_statuses)]

        latest = df.sort_values("created_at", ascending=False).head(1) if "created_at" in df.columns else df.head(1)

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Latest Status", metric_value(latest, "status"))
        col2.metric("Symbol", metric_value(latest, "symbol"))
        col3.metric("DNA Step", metric_value(latest, "dna_step"))
        col4.metric("DNA Signal", metric_value(latest, "dna_signal"))
        col5.metric("Action", metric_value(latest, "action"))

        # Recommended column order.
        preferred_cols = [
            "created_at",
            "status",
            "action",
            "reason",
            "symbol",
            "dna_step",
            "dna_signal",
            "last_price",
            "quantity",
            "value_now",
            "rebalance_amount",
            "side",
            "order_quantity",
            "order_status",
            "order_id",
            "client_order_id",
            "baseline_pnl",
            "strategy_id",
            "state_document",
            "document_id",
        ]
        display_cols = [c for c in preferred_cols if c in df.columns]
        extra_cols = [c for c in df.columns if c not in display_cols]
        df_display = df[display_cols + extra_cols]

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
        )

        csv = df_display.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "⬇️ Download CSV",
            csv,
            file_name="webull_trade_logs.csv",
            mime="text/csv",
        )

with tabs[1]:
    st.subheader("🧬 Bot State")

    state_df = read_state(state_collection_name)
    if state_df.empty:
        st.warning("ยังไม่มี state document")
    else:
        st.dataframe(state_df, use_container_width=True, hide_index=True)

        for _, row in state_df.iterrows():
            with st.expander(f"State: {row.get('document_id', '-')}", expanded=True):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("DNA Step", row.get("dna_step", "-"))
                col2.metric("Last Signal", row.get("last_signal", "-"))
                col3.metric("Symbol", row.get("symbol", "-"))
                col4.metric("Strategy", row.get("strategy_id", "-"))

with tabs[2]:
    st.subheader("📊 Analytics")

    df = read_trade_logs(collection_name=collection_name, limit=limit)

    if df.empty:
        st.warning("ยังไม่มีข้อมูลสำหรับทำกราฟ")
    else:
        if "status" in df.columns:
            st.markdown("### Status Count")
            status_count = df["status"].fillna("UNKNOWN").value_counts()
            st.bar_chart(status_count)

        if "created_at" in df.columns and "last_price" in df.columns:
            st.markdown("### Last Price")
            price_df = df.copy()
            price_df["last_price"] = pd.to_numeric(price_df["last_price"], errors="coerce")
            price_df = price_df.dropna(subset=["created_at", "last_price"])
            price_df = price_df.sort_values("created_at")
            if not price_df.empty:
                st.line_chart(price_df.set_index("created_at")["last_price"])
            else:
                st.info("ยังไม่มี field last_price ใน logs ชุดนี้")

        if "created_at" in df.columns and "rebalance_amount" in df.columns:
            st.markdown("### Rebalance Amount")
            reb_df = df.copy()
            reb_df["rebalance_amount"] = pd.to_numeric(
                reb_df["rebalance_amount"], errors="coerce"
            )
            reb_df = reb_df.dropna(subset=["created_at", "rebalance_amount"])
            reb_df = reb_df.sort_values("created_at")
            if not reb_df.empty:
                st.line_chart(reb_df.set_index("created_at")["rebalance_amount"])
            else:
                st.info("ยังไม่มี field rebalance_amount ใน logs ชุดนี้")

        if "action" in df.columns:
            st.markdown("### Action Count")
            action_count = df["action"].fillna("UNKNOWN").value_counts()
            st.bar_chart(action_count)

with tabs[3]:
    st.subheader("🛠️ Debug")

    st.markdown(
        """
        ใช้หน้านี้เช็กว่า Streamlit อ่าน Firestore ได้หรือไม่

        Checklist:
        - Streamlit Secrets มี `[firebase_service_account]`
        - Service account มี role `roles/datastore.viewer`
        - Project ID ใน service account คือ `webull-bot-uat`
        - Collection ชื่อ `trade_logs`
        """
    )

    try:
        db = init_firestore()
        st.success("Firestore client initialized successfully")
        st.write("Collections:")
        collections = [c.id for c in db.collections()]
        st.json(collections)
    except Exception as exc:
        st.error("Firestore connection failed")
        st.exception(exc)
