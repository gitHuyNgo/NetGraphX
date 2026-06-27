"""
app.py
------
NetGraphX Streamlit dashboard — Network Knowledge Graph Explorer.

Layout (inspired by the reference screenshot, adapted to our data):
  ┌─ Sidebar ──────────┬─ Main ────────────────────────────────────────┐
  │ Graph Config       │  [Metrics row]                                │
  │  · View selector   │  ┌────────────────────────────────────────┐   │
  │  · Node scale      │  │      Network Topology Graph            │   │
  │  · Refresh         │  │      (vis.js hierarchical, filtered)   │   │
  │ Search Nodes       │  └────────────────────────────────────────┘   │
  │ Filters            │  ┌────────────────┐  ┌────────────────────┐   │
  │  · Role layers     │  │ Device Details │  │  RAG Assistant     │   │
  │  · SPOF / VLAN     │  │ (sidebar pick) │  │  (chatbot)         │   │
  │ NetBox Sync Status │  └────────────────┘  └────────────────────┘   │
  │ [Admin] Rules Ed.  │                                               │
  └────────────────────┴───────────────────────────────────────────────┘

RBAC:
  admin    — all features, Done/Sync button, rules editor, user list
  engineer — graph, chatbot, device inspector (read-only)
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from neo4j import GraphDatabase
from config.settings import auth_config, neo4j_config, webhook_config
from src.core.auth.users import authenticate, get_role, list_users
from src.engine.graph_builder import (
    _LAYER_LABELS,
    _NODE_COLORS,
    _assign_layer,
)
from src.ui.vis_component.renderer import build_vis_html
from src.rag.embedder import NodeEmbedder
from src.rag.query_parser import MultiIntentQueryParser
from src.rag.retriever import HybridRetriever
from src.rag.synthesizer import LLMSynthesizer
from src.api.webhook.state import get_status as get_webhook_status

# ─────────────────────────────────────────────────────────────────────────────
# Page config  (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NetGraphX — Network Explorer",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Global CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* ── Main area ── */
    .main .block-container {
        background: #f5f6fa;
        padding-top: 1rem;
        padding-bottom: 0.5rem;
    }
    .stApp { background: #f5f6fa; }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: #ffffff !important;
        border-right: 1px solid #dde1e7 !important;
        box-shadow: 2px 0 8px rgba(0,0,0,0.05);
    }
    [data-testid="stSidebar"] * { color: #2c3e50 !important; }
    [data-testid="stSidebarContent"] { padding: 0 12px 20px; }

    /* ── Buttons ── */
    .stButton > button {
        border-radius: 7px; font-weight: 600; font-size: 12px;
        transition: all 0.18s;
        border: 1px solid #cdd0d5 !important;
        background: #f0f2f5 !important;
        color: #2c3e50 !important;
    }
    .stButton > button:hover {
        background: #e2e5ea !important;
        border-color: #1565c0 !important;
        transform: translateY(-1px);
        box-shadow: 0 3px 10px rgba(0,0,0,0.12);
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg,#1565c0,#1976d2) !important;
        border: none !important;
        color: white !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg,#1976d2,#1e88e5) !important;
    }

    /* ── Metric cards ── */
    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #dde1e7;
        border-radius: 10px;
        padding: 14px 18px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    [data-testid="stMetricLabel"] { font-size: 11px !important; color: #5a6474 !important; }
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; font-weight: 700; color: #1a2535 !important; }

    /* ── Section headers ── */
    .section-hdr {
        font-size: 10.5px; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.8px; color: #8e99aa;
        padding: 6px 0 4px; margin-bottom: 4px;
        border-bottom: 1px solid #eaecf0;
    }

    /* ── Role badges ── */
    .badge-admin {
        background: linear-gradient(135deg,#c62828,#b71c1c);
        color: #fff; padding: 2px 9px; border-radius: 10px;
        font-size: 10px; font-weight: 700; letter-spacing: 0.4px;
    }
    .badge-engineer {
        background: linear-gradient(135deg,#1565c0,#0d47a1);
        color: #fff; padding: 2px 9px; border-radius: 10px;
        font-size: 10px; font-weight: 700; letter-spacing: 0.4px;
    }

    /* ── Webhook banners ── */
    .wh-pending {
        background: #fff8e1; border: 1px solid #f9a825;
        border-radius: 8px; padding: 9px 12px;
        color: #6d4c00; font-size: 12px; line-height: 1.6;
    }
    .wh-ok {
        background: #e8f5e9; border: 1px solid #388e3c;
        border-radius: 8px; padding: 9px 12px;
        color: #1b5e20; font-size: 12px; line-height: 1.6;
    }

    /* ── Device panel ── */
    .device-card {
        background: #ffffff;
        border: 1px solid #dde1e7;
        border-radius: 10px;
        padding: 16px 18px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .device-field {
        display: flex; justify-content: space-between;
        padding: 5px 0; border-bottom: 1px solid #f0f2f5;
        font-size: 12.5px;
    }
    .device-field:last-child { border-bottom: none; }
    .device-field .lbl { color: #8e99aa; }
    .device-field .val { color: #1a2535; font-weight: 500; text-align: right; }
    .spof-badge {
        background: #fff3e0; border: 1px solid #f57f17;
        color: #e65100; border-radius: 6px;
        padding: 2px 8px; font-size: 10px; font-weight: 700;
    }
    .ok-badge {
        background: #e8f5e9; border: 1px solid #388e3c;
        color: #1b5e20; border-radius: 6px;
        padding: 2px 8px; font-size: 10px; font-weight: 700;
    }

    /* ── Chat ── */
    .stChatMessage {
        background: #ffffff !important;
        border: 1px solid #dde1e7 !important;
        border-radius: 10px !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
    }

    /* ── Inputs / Selects ── */
    [data-testid="stSelectbox"] > div > div,
    [data-testid="stTextInput"] > div > div {
        border-radius: 7px !important;
        border: 1px solid #cdd0d5 !important;
        background-color: #ffffff !important;
        overflow: hidden !important;
    }
    [data-testid="stSelectbox"] div[data-baseweb="select"],
    [data-testid="stTextInput"] div[data-baseweb="input"],
    [data-testid="stTextInput"] div[data-baseweb="base-input"],
    [data-testid="stTextInput"] input {
        background-color: transparent !important;
        border: none !important;
        color: #2c3e50 !important;
    }
    [data-testid="stSlider"] .stSlider { color: #2c3e50 !important; }

    /* Checkbox text */
    [data-testid="stCheckbox"] span { color: #2c3e50 !important; font-size: 12.5px !important; }

    /* Divider */
    hr { border-color: #eaecf0 !important; }

    /* Caption text */
    .stCaption, .css-10trblm { color: #8e99aa !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Cached resources
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_neo4j_driver():
    return GraphDatabase.driver(
        neo4j_config.NEO4J_URI,
        auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD),
    )


@st.cache_resource
def get_embedder():
    return NodeEmbedder()


@st.cache_resource
def get_query_parser():
    return MultiIntentQueryParser()


@st.cache_resource
def get_retriever(_driver, _embedder):
    return HybridRetriever(_driver, _embedder)


@st.cache_resource
def get_synthesizer():
    return LLMSynthesizer()


# ─────────────────────────────────────────────────────────────────────────────
# Topology data loader
# ─────────────────────────────────────────────────────────────────────────────
from pathlib import Path
_TOPO_DATA_FILE = str(Path(__file__).parent.parent.parent / "data" / "storage" / "topology_data.json")
_META_FILE      = str(Path(__file__).parent.parent.parent / "data" / "storage" / "dominant_meta.pkl")


@st.cache_data(ttl=30)
def load_topology_data() -> Optional[Dict]:
    """Load topology_data.json with a 30-second cache TTL."""
    if os.path.exists(_TOPO_DATA_FILE):
        with open(_TOPO_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


@st.cache_data(ttl=30)
def load_model_health() -> Optional[Dict]:
    """Load dominant_meta.pkl and return training metrics dict (30-second TTL)."""
    if os.path.exists(_META_FILE):
        try:
            import joblib
            return joblib.load(_META_FILE)
        except Exception:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Session state bootstrap
# ─────────────────────────────────────────────────────────────────────────────
def _init_session():
    defaults = {
        "authenticated": False,
        "username":       "",
        "role":           "",
        "messages":       [
            {
                "role": "assistant",
                "content": (
                    "Xin chào! Tôi là trợ lý AI giám sát mạng NetGraphX.\n\n"
                    "Bạn có thể hỏi tôi về:\n"
                    "- 📍 Danh sách thiết bị và kết nối\n"
                    "- ⚠️ Điểm đơn lỗi (SPOF)\n"
                    "- 🔗 Vấn đề VLAN mismatch\n"
                    "- 📊 Phân tích topo mạng"
                ),
            }
        ],
        "selected_device": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# ── LOGIN PAGE ────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _render_login():
    col_l, col_m, col_r = st.columns([1, 1.1, 1])
    with col_m:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown(
            """
            <div style='text-align:center; margin-bottom:36px;'>
              <div style='font-size:48px; margin-bottom:8px;'>🔗</div>
              <h1 style='font-size:2rem; font-weight:800; margin:0;
                         background: linear-gradient(90deg,#1565c0,#1976d2);
                         -webkit-background-clip:text; -webkit-text-fill-color:transparent;'>
                NetGraphX
              </h1>
              <p style='color:#5a6474; font-size:13px; margin-top:6px;'>
                Network Knowledge Graph Explorer
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input(
                "Username", placeholder="Enter username", label_visibility="collapsed"
            )
            password = st.text_input(
                "Password", type="password", placeholder="Enter password",
                label_visibility="collapsed"
            )
            submitted = st.form_submit_button(
                "🔐  Sign In", use_container_width=True, type="primary"
            )
            if submitted:
                if authenticate(username, password):
                    st.session_state.authenticated = True
                    st.session_state.username = username
                    st.session_state.role = get_role(username)
                    st.rerun()
                else:
                    st.error("❌  Invalid credentials.")

        st.markdown(
            "<p style='text-align:center; color:#8e99aa; font-size:11px; margin-top:14px;'>"
            "Contact your network administrator to request access.</p>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# ── SIDEBAR ──────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _render_sidebar(topo: Optional[Dict]) -> Dict:
    """
    Render the sidebar and return a dict of all current filter/config values.
    """
    username = st.session_state.username
    role     = st.session_state.role

    filters = {}

    with st.sidebar:
        # ── User identity ──────────────────────────────────────────────────
        badge_cls = "badge-admin" if role == "admin" else "badge-engineer"
        st.markdown(
            f"""
            <div style='padding:10px 12px; background:#f5f6fa; border-radius:9px;
                        border:1px solid #dde1e7; margin-bottom:12px; margin-top:8px;'>
              <div style='font-size:13px; font-weight:600; color:#1a2535;'>👤 {username}</div>
              <div style='margin-top:5px;'>
                <span class='{badge_cls}'>{role.upper()}</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("🚪 Sign Out", use_container_width=True):
            for k in ("authenticated", "username", "role", "messages", "selected_device"):
                st.session_state[k] = False if k == "authenticated" else (
                    [] if k == "messages" else ""
                )
            st.rerun()

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── Graph Configuration ────────────────────────────────────────────
        st.markdown("<div class='section-hdr'>Graph Configuration</div>", unsafe_allow_html=True)

        view_options = [
            "Full Topology",
            "Core & Distribution",
            "Access & Endpoints",
            "SPOF Focus",
        ]
        filters["view"] = st.selectbox(
            "Select View", view_options, key="view_select", label_visibility="collapsed"
        )

        filters["node_scale"] = st.slider(
            "Node Scaling", min_value=0.5, max_value=2.5, value=1.0, step=0.1,
            key="node_scale_slider"
        )

        if st.button("🔄  Refresh Graph", use_container_width=True):
            load_topology_data.clear()
            st.rerun()

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── Search Nodes ───────────────────────────────────────────────────
        st.markdown("<div class='section-hdr'>Search & Inspect</div>", unsafe_allow_html=True)

        # Site filter dropdown
        all_sites = sorted({
            n.get("_site", "") or ""
            for n in (topo["nodes"] if topo else [])
            if n.get("_site")
        })
        site_options = ["All Sites"] + all_sites
        filters["site"] = st.selectbox(
            "Filter by Site",
            site_options,
            key="site_select",
        )
        selected_site = filters["site"]

        # Device picker (narrowed to chosen site)
        if topo:
            if selected_site == "All Sites":
                eligible = [n["id"] for n in topo["nodes"]]
            else:
                eligible = [
                    n["id"] for n in topo["nodes"]
                    if (n.get("_site") or "") == selected_site
                ]
        else:
            eligible = []
        device_names = ["— None —"] + sorted(eligible)

        selected_idx = 0
        if st.session_state.get("selected_device") in device_names:
            selected_idx = device_names.index(st.session_state.get("selected_device"))

        picked = st.selectbox(
            "Inspect Device", device_names, index=selected_idx,
            label_visibility="collapsed",
        )

        # Manually sync the selectbox to the session state
        if picked != "— None —" and picked != st.session_state.get("selected_device"):
            st.session_state["selected_device"] = picked
            st.rerun()
        elif picked == "— None —" and st.session_state.get("selected_device") is not None:
            st.session_state["selected_device"] = None
            st.rerun()

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── Filters ────────────────────────────────────────────────────────
        st.markdown("<div class='section-hdr'>Filters</div>", unsafe_allow_html=True)

        filters["show_core"]   = st.checkbox("Show Core / Spine",     value=True, key="f_core")
        filters["show_dist"]   = st.checkbox("Show Distribution",      value=True, key="f_dist")
        filters["show_access"] = st.checkbox("Show Access / Edge",     value=True, key="f_access")
        filters["show_ep"]     = st.checkbox("Show Endpoints",         value=True, key="f_ep")
        filters["show_spof"]   = st.checkbox("Highlight SPOF Nodes",   value=True, key="f_spof")
        filters["show_vlan"]   = st.checkbox("Highlight VLAN Mismatches", value=True, key="f_vlan")

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── Webhook status ─────────────────────────────────────────────────
        st.markdown("<div class='section-hdr'>NetBox Sync Status</div>", unsafe_allow_html=True)
        _render_webhook_panel(role)

        # ── Admin-only sections ────────────────────────────────────────────
        if role == "admin":
            st.markdown("<hr>", unsafe_allow_html=True)
            _render_ai_health_panel()
            st.markdown("<hr>", unsafe_allow_html=True)
            _render_rules_editor()
            st.markdown("<hr>", unsafe_allow_html=True)
            _render_user_list()

    return filters


# ─────────────────────────────────────────────────────────────────────────────
# ── WEBHOOK PANEL ────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _render_webhook_panel(role: str):
    wh          = get_webhook_status()
    pending     = wh.get("pending", False)
    last_change = wh.get("last_change_utc")
    last_sync   = wh.get("last_sync_utc")
    event_type  = wh.get("last_event_type", "—")

    if pending:
        st.markdown(
            f"""<div class='wh-pending'>
              ⚡ <b>Pending changes</b><br>
              <small>Changed: {_fmt_utc(last_change)}</small><br>
              <small>Event: <code>{event_type}</code></small><br>
              <small>Auto-sync in ≤{webhook_config.WEBHOOK_DEBOUNCE_MINUTES} min</small>
            </div>""",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        if role == "admin":
            if st.button("✅  Done — Sync Now", type="primary", use_container_width=True):
                _trigger_done()
    else:
        st.markdown(
            f"""<div class='wh-ok'>
              ✅ <b>Topology up-to-date</b><br>
              <small>Last sync: {_fmt_utc(last_sync) if last_sync else 'Never'}</small>
            </div>""",
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        if role == "admin":
            if st.button("🔄  Force Sync", use_container_width=True):
                _trigger_done(force=True)

    if st.button("↻  Refresh Status", use_container_width=True, key="wh_refresh"):
        st.rerun()


def _trigger_done(force: bool = False):
    url = f"http://localhost:{webhook_config.WEBHOOK_PORT}/webhook/done"
    if force:
        url += "?force=true"
    headers = {}
    if webhook_config.WEBHOOK_SECRET:
        headers["X-NetBox-Key"] = webhook_config.WEBHOOK_SECRET
    try:
        resp = requests.post(url, headers=headers, timeout=5)
        data = resp.json()
        msg  = data.get("message", "Sync triggered.")
        if resp.status_code in (200, 202):
            st.success(f"✅  {msg}")
        else:
            st.error(f"❌  {data.get('error', 'Unknown error.')}")
    except requests.ConnectionError:
        st.error("❌  Webhook server unreachable. Start it with `python -m src.api.webhook.server`.")
    except Exception as exc:
        st.error(f"❌  {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# ── ADMIN PANELS ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _render_rules_editor():
    st.markdown("<div style='margin-bottom:8px'><b>🛡️ Audit Rules</b></div>", unsafe_allow_html=True)
    if st.button("Open Rule Editor", use_container_width=True):
        st.session_state.current_page = "rule_editor"
        st.rerun()


def _render_user_list():
    with st.expander("👥  Registered Users", expanded=False):
        for u in list_users():
            cls = "badge-admin" if u["role"] == "admin" else "badge-engineer"
            st.markdown(
                f"<div style='padding:4px 0; font-size:12.5px;'>"
                f"<b>{u['username']}</b>&nbsp;"
                f"<span class='{cls}'>{u['role'].upper()}</span></div>",
                unsafe_allow_html=True,
            )
        st.caption("Edit `config/users.yaml` to manage users.")


# ─────────────────────────────────────────────────────────────────────────────
# ── AI MODEL HEALTH PANEL ────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _render_ai_health_panel():
    """Admin-only sidebar panel showing live DOMINANT model training metrics."""
    meta = load_model_health()

    st.markdown("<div class='section-hdr'>🤖 AI Model Health</div>", unsafe_allow_html=True)

    if meta is None:
        st.markdown(
            "<div style='font-size:11.5px; color:#8e99aa; padding:6px 0;'>"
            "No trained model found. Run <code>train.py</code> to generate one.</div>",
            unsafe_allow_html=True,
        )
        return

    pr_auc       = meta.get('pr_auc', 0.0)
    roc_auc      = meta.get('roc_auc', 0.0)
    best_alpha   = meta.get('alpha', '—')
    n_nodes      = meta.get('n_nodes', '—')
    n_anomalies  = meta.get('n_anomalies', '—')
    contamination = meta.get('contamination_rate', 0.0)
    n_wl         = meta.get('n_whitelisted', 0)
    tp           = meta.get('tp', '—')
    fp           = meta.get('fp', '—')
    prec_k       = meta.get('precision_at_k', 0.0)
    recall_k     = meta.get('recall_at_top5pct', 0.0)
    trained_at   = meta.get('trained_at', '')

    # Parse timestamp
    trained_str = '—'
    if trained_at:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(trained_at)
            trained_str = dt.strftime('%Y-%m-%d %H:%M UTC')
        except Exception:
            trained_str = trained_at

    # ── PR-AUC Gauge ────────────────────────────────────────────────────
    random_floor = contamination if contamination else 0.02
    # Normalise to [0, 1] relative to realistic ceiling of 0.65
    bar_pct = min(pr_auc / 0.65, 1.0)
    bar_color = (
        '#e53935' if pr_auc < random_floor * 2 else
        '#f9a825' if pr_auc < random_floor * 5 else
        '#43a047'
    )

    st.markdown(
        f"""
        <div style='background:#f5f6fa; border:1px solid #dde1e7; border-radius:9px;
                    padding:10px 12px; margin-bottom:8px;'>
          <div style='font-size:10.5px; color:#8e99aa; font-weight:700;
                      text-transform:uppercase; letter-spacing:0.6px;
                      margin-bottom:6px;'>PR-AUC Score</div>
          <div style='font-size:1.6rem; font-weight:800; color:{bar_color};
                      line-height:1.1;'>{pr_auc:.4f}</div>
          <div style='background:#e0e0e0; border-radius:4px;
                      height:6px; margin:6px 0 4px;'>
            <div style='background:{bar_color}; width:{bar_pct*100:.1f}%;
                        height:6px; border-radius:4px; transition:width 0.4s;'></div>
          </div>
          <div style='font-size:10px; color:#8e99aa;'>
            Random floor: {random_floor:.3f} &nbsp;|&nbsp;
            Lift: <b style='color:{bar_color};'>{pr_auc/random_floor:.1f}×</b>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Key metrics grid ─────────────────────────────────────────────────
    rows = [
        ("Best α (grid search)",  f"{best_alpha}"),
        ("ROC-AUC",               f"{roc_auc:.4f}"),
        ("Contamination rate",    f"{contamination*100:.1f}%"),
        ("Graph size",            f"{n_nodes} nodes"),
        ("Ground-truth anomalies",f"{n_anomalies}"),
        ("Whitelisted (masked)",  f"{n_wl}"),
        ("TP caught @ Top-5%",    f"{tp}  (recall {recall_k:.0%})"),
        ("FP flagged @ Top-5%",   f"{fp}  (prec {prec_k:.0%})"),
        ("Last trained",          trained_str),
    ]
    rows_html = "".join(
        f"<div class='device-field'>"
        f"<span class='lbl'>{lbl}</span>"
        f"<span class='val'>{val}</span></div>"
        for lbl, val in rows
    )
    st.markdown(f"<div class='device-card'>{rows_html}</div>", unsafe_allow_html=True)

    # ── Alpha grid search results table ─────────────────────────────────
    grid = meta.get('grid_search_results')
    if grid:
        with st.expander("📊 Alpha Grid Search Results", expanded=False):
            gdf = (
                __import__('pandas').DataFrame(grid)
                .rename(columns={'alpha': 'α', 'pr_auc': 'PR-AUC', 'roc_auc': 'ROC-AUC'})
                .sort_values('PR-AUC', ascending=False)
                .reset_index(drop=True)
            )
            # Bold best row
            best_row = gdf.iloc[0]
            st.dataframe(
                gdf.style.format({'α': '{:.1f}', 'PR-AUC': '{:.4f}', 'ROC-AUC': '{:.4f}'})
                         .highlight_max(subset=['PR-AUC'], color='#c8e6c9'),
                use_container_width=True,
                hide_index=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# ── GRAPH RENDERING ───────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
_LAYER_SHOW_MAP = {
    "show_core":   0,
    "show_dist":   1,
    "show_access": 2,
    "show_ep":     3,
}


def _apply_filters(topo: Dict, filters: Dict) -> tuple:
    """Return (filtered_nodes, filtered_edges) respecting sidebar filter state."""
    view   = filters.get("view", "Full Topology")
    spof   = set(topo.get("spof", []))
    vm_raw = topo.get("vlan_mismatches", [])

    # Build mismatch pair set
    mismatch_pairs = set()
    for conn in vm_raw:
        if " <-> " in str(conn):
            a, b = str(conn).split(" <-> ", 1)
            mismatch_pairs.add((a.strip(), b.strip()))
            mismatch_pairs.add((b.strip(), a.strip()))

    # ── View-based coarse filtering ────────────────────────────────────
    def _layer_ok(layer: int) -> bool:
        if view == "Core & Distribution":
            return layer <= 1
        if view == "Access & Endpoints":
            return layer >= 2
        return True  # Full Topology + SPOF Focus include all

    # ── Checkbox-based fine filtering ──────────────────────────────────
    def _checkbox_ok(layer: int) -> bool:
        key = next((k for k, l in _LAYER_SHOW_MAP.items() if l == layer), None)
        if key is None:
            return True
        return filters.get(key, True)

    # ── SPOF focus: keep SPOF nodes + their direct neighbours ──────────
    if view == "SPOF Focus":
        spof_neighbors = set(spof)
        for raw_node in topo["nodes"]:
            if raw_node["id"] in spof:
                # find edges touching this node
                for e in topo["edges"]:
                    if e["from"] == raw_node["id"]:
                        spof_neighbors.add(e["to"])
                    elif e["to"] == raw_node["id"]:
                        spof_neighbors.add(e["from"])
        allowed_ids = spof_neighbors
    else:
        allowed_ids = None  # no restriction

    # ── Filter nodes ──────────────────────────────────────────────────
    site_filter = filters.get("site", "All Sites")

    filtered_nodes = []
    kept_ids = set()
    for n in topo["nodes"]:
        layer = n.get("_layer", 2)
        if not _layer_ok(layer):
            continue
        if not _checkbox_ok(layer):
            continue
        if allowed_ids is not None and n["id"] not in allowed_ids:
            continue
        # Site filter guard
        if site_filter != "All Sites" and (n.get("_site") or "") != site_filter:
            continue

        node = dict(n)

        # Strip SPOF styling if highlight is OFF
        if not filters.get("show_spof", True) and n.get("_is_spof"):
            node["color"] = {
                "background": _NODE_COLORS.get(layer, "#1e88e5"),
                "border": "#000",
            }
            node["label"] = n["id"]  # remove [SPOF ⚠] suffix

        if n.get("_is_predicted_rogue"):
            if not n.get("_human_reviewed"):
                node["color"] = {
                    "background": "#ff1744", # bright red
                    "border": "#ff1744",
                    "highlight": {"background": "#ffffff", "border": "#ff1744"}
                }
                node["label"] = n["id"] + "\n[? ROGUE]"
            elif n.get("_is_confirmed_rogue"):
                node["color"] = {
                    "background": "#b71c1c", # dark red
                    "border": "#000000"
                }
                node["label"] = n["id"] + "\n[ROGUE]"

        filtered_nodes.append(node)
        kept_ids.add(n["id"])

    # ── Filter edges ──────────────────────────────────────────────────
    filtered_edges = []
    for e in topo["edges"]:
        if e["from"] not in kept_ids or e["to"] not in kept_ids:
            continue

        edge = dict(e)

        # Recolor VLAN mismatch edges if toggle is OFF
        is_mismatch = (e["from"], e["to"]) in mismatch_pairs
        if not filters.get("show_vlan", True) and is_mismatch:
            edge["color"] = {"color": "#78909c", "highlight": "#ffffff", "hover": "#b0bec5"}
            edge["width"] = 1.5
            edge["label"] = f"{e.get('_src_if','?')} ↔ {e.get('_tgt_if','?')}"

        filtered_edges.append(edge)

    return filtered_nodes, filtered_edges


def _render_graph(topo: Optional[Dict], filters: Dict):
    """Render the vis.js graph inline with current filters applied."""
    if not topo:
        st.warning(
            "No topology data found. Run `python main.py --run-engine` to generate `topology_data.json`, "
            "or click **Done — Sync Now** if webhook changes are pending."
        )
        return

    vis_nodes, vis_edges = _apply_filters(topo, filters)

    if not vis_nodes:
        st.info("No devices match current filters. Adjust the filter settings in the sidebar.")
        return

    meta = {
        "spof_count":     sum(1 for n in vis_nodes if n.get("_is_spof")),
        "mismatch_count": sum(1 for e in vis_edges if e.get("_mismatch")),
    }

    highlight = st.session_state.get("selected_device")
    if highlight and highlight not in {n["id"] for n in vis_nodes}:
        highlight = None

    html = build_vis_html(
        vis_nodes=vis_nodes,
        vis_edges=vis_edges,
        meta=meta,
        highlight_node=None, # Highlight is handled dynamically via JS now
        node_scale=filters.get("node_scale", 1.0),
    )

    from src.ui.vis_component import vis_network
    
    clicked_node = vis_network(html=html, highlight=highlight, height=460, key="vis_net")
    
    if clicked_node is not None and clicked_node != "":
        if st.session_state.get("selected_device") != clicked_node:
            st.session_state["selected_device"] = clicked_node
            st.rerun()
    elif clicked_node == "":
        if st.session_state.get("selected_device") is not None:
            st.session_state["selected_device"] = None
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# ── METRICS ROW ───────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _render_metrics(topo: Optional[Dict]):
    if not topo:
        return

    nodes      = topo.get("nodes", [])
    edges      = topo.get("edges", [])
    spof_count = len(topo.get("spof", []))
    vm_count   = len([x for x in topo.get("vlan_mismatches", []) if x])
    gen_at     = topo.get("generated_at", "")
    gen_str    = _fmt_utc(gen_at) if gen_at else "—"

    # Count by layer
    layer_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    for n in nodes:
        l = n.get("_layer", 2)
        layer_counts[l] = layer_counts.get(l, 0) + 1

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("🖥️ Devices",     len(nodes))
    m2.metric("🔗 Cables",      len(edges))
    m3.metric("🔴 Core",        layer_counts[0])
    m4.metric("🟠 Distribution", layer_counts[1])
    m5.metric("⚠️ SPOFs",        spof_count,
              delta=f"{'Critical' if spof_count else 'None'}",
              delta_color="inverse")
    m6.metric("🔀 VLAN Issues", vm_count,
              delta=f"{'Critical' if vm_count else 'None'}",
              delta_color="inverse")

    st.caption(f"Last topology sync: {gen_str}")


# ─────────────────────────────────────────────────────────────────────────────
# ── DEVICE DETAILS PANEL ──────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _update_rogue_status(node_id: str, is_confirmed: bool):
    driver = get_neo4j_driver()
    with driver.session() as session:
        session.run(
            """
            MATCH (d:Device {name: $node_id})
            SET d.is_confirmed_rogue = $is_confirmed,
                d.human_reviewed = true
            """,
            node_id=node_id,
            is_confirmed=is_confirmed
        )
    topo = load_topology_data()
    if topo:
        for n in topo.get("nodes", []):
            if n["id"] == node_id:
                n["_is_confirmed_rogue"] = is_confirmed
                n["_human_reviewed"] = True
                break
        with open(_TOPO_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(topo, f, ensure_ascii=False)
    load_topology_data.clear()
    st.rerun()

def _render_device_details(topo: Optional[Dict]):
    hdr_col, vi_col = st.columns([0.75, 0.25])
    with hdr_col:
        st.markdown(
            "<div style='font-size:13px; font-weight:700; color:#1a2535; "
            "margin-bottom:10px; margin-top:6px;'>📋 Device Details</div>",
            unsafe_allow_html=True,
        )
        
    selected = st.session_state.get("selected_device")
    
    if selected:
        with vi_col:
            if st.button("Q&A", use_container_width=True, type="primary", help="Hỏi chatbot về thiết bị này"):
                st.session_state["trigger_chat"] = f"Cho tôi biết tất cả các thông tin về node {selected}"

    if not selected or not topo:
        st.markdown(
            "<div class='device-card' style='color:#8e99aa; font-size:12px; text-align:center; "
            "padding:30px;'>Select a device from the sidebar<br>to inspect its details.</div>",
            unsafe_allow_html=True,
        )
        return

    # Find node data
    node_data = next(
        (n for n in topo.get("nodes", []) if n["id"] == selected), None
    )
    if not node_data:
        st.warning(f"Device `{selected}` not found in topology data.")
        return

    is_spof = node_data.get("_is_spof", False)
    layer   = node_data.get("_layer", 2)
    layer_name  = _LAYER_LABELS.get(layer, "Unknown")
    layer_color = _NODE_COLORS.get(layer, "#1e88e5")

    spof_html = (
        "<span class='spof-badge'>⚠ SPOF</span>"
        if is_spof else
        "<span class='ok-badge'>✓ Healthy</span>"
    )

    # Find connected edges
    connected_edges = [
        e for e in topo.get("edges", [])
        if e.get("from") == selected or e.get("to") == selected
    ]
    connected_devices = []
    for e in connected_edges:
        peer = e["to"] if e["from"] == selected else e["from"]
        connected_devices.append(peer)

    fields = [
        ("Name",          node_data["id"]),
        ("Role",          node_data.get("_role") or "—"),
        ("Layer",         f"L{layer} — {layer_name}"),
        ("IP Address",    node_data.get("_ip") or "—"),
        ("Status",        node_data.get("_status") or "—"),
        ("Vendor",        node_data.get("_vendor") or "—"),
        ("Site",          node_data.get("_site") or "—"),
        ("Rack",          node_data.get("_rack") or "—"),
        ("Connections",   str(len(connected_devices))),
    ]
    
    if node_data.get("_is_predicted_rogue"):
        fields.append(("AI Prediction", "🚨 ROGUE DEVICE"))
        fields.append(("Anomaly Score", f"{node_data.get('_anomaly_score', 0):.2f}"))
        # Show topology violation reason if present
        if node_data.get("_topology_violation"):
            fields.append(("⚠️ Topo Violation", node_data.get("_violation_reason", "Illegal cross-layer connection")))
        status = "Pending Review"
        if node_data.get("_human_reviewed"):
            if node_data.get("_is_confirmed_rogue"):
                status = "✅ Confirmed Rogue"
            else:
                status = "❌ Rejected (Normal)"
        fields.append(("Human Status", status))

    fields_html = "".join(
        f"<div class='device-field'>"
        f"<span class='lbl'>{lbl}</span>"
        f"<span class='val'>{val}</span>"
        f"</div>"
        for lbl, val in fields
    )

    st.markdown(
        f"""
        <div class='device-card'>
          <div style='display:flex; align-items:center; gap:10px; margin-bottom:12px;'>
            <div style='width:14px; height:14px; border-radius:50%;
                        background:{layer_color}; flex-shrink:0;'></div>
            <b style='font-size:14px; color:#1a2535;'>{node_data["id"]}</b>
            &nbsp;{spof_html}
          </div>
          {fields_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not node_data.get("_human_reviewed"):
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:12px; font-weight:700; color:#1a2535; margin-bottom:8px;'>Human In The Loop Verification</div>", unsafe_allow_html=True)
        
        if node_data.get("_is_predicted_rogue"):
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🚨 Confirm Rogue", key="btn_confirm_rogue", type="primary", use_container_width=True):
                    _update_rogue_status(selected, True)
            with c2:
                if st.button("✅ White-list / False Positive", key="btn_reject_rogue", use_container_width=True):
                    _update_rogue_status(selected, False)
        else:
            if st.button("🚨 Flag as Rogue (Missed Anomaly)", key="btn_mark_rogue_fn", type="primary", use_container_width=True):
                _update_rogue_status(selected, True)

    # ── Active Learning Retrain Panel ─────────────────────────────────────
    has_feedback = any(n.get("_human_reviewed") for n in topo.get("nodes", []))
    whitelisted_count = sum(
        1 for n in topo.get("nodes", [])
        if n.get("_human_reviewed") and not n.get("_is_confirmed_rogue")
    )
    confirmed_count = sum(
        1 for n in topo.get("nodes", [])
        if n.get("_human_reviewed") and n.get("_is_confirmed_rogue")
    )

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(
        "<div style='font-size:12px; font-weight:700; color:#1a2535; margin-bottom:8px;'>"
        "🔁 Active Learning Retrain"
        "</div>",
        unsafe_allow_html=True,
    )

    # Feedback summary badges
    badge_html = (
        f"<div style='display:flex; gap:8px; margin-bottom:10px;'>"
        f"<span style='background:#e8f5e9; border:1px solid #388e3c; color:#1b5e20;"
        f"  border-radius:6px; padding:2px 8px; font-size:10.5px; font-weight:700;'>"
        f"✅ {whitelisted_count} Whitelisted</span>"
        f"<span style='background:#ffebee; border:1px solid #c62828; color:#b71c1c;"
        f"  border-radius:6px; padding:2px 8px; font-size:10.5px; font-weight:700;'>"
        f"🚨 {confirmed_count} Confirmed Rogue</span>"
        f"</div>"
    )
    st.markdown(badge_html, unsafe_allow_html=True)

    # Show current model PR-AUC as a before-value reference
    meta_before = load_model_health()
    pr_before = meta_before.get('pr_auc', None) if meta_before else None
    alpha_before = meta_before.get('alpha', None) if meta_before else None
    if pr_before is not None:
        st.markdown(
            f"<div style='font-size:11px; color:#5a6474; margin-bottom:10px;'>"
            f"Current model: <b>PR-AUC = {pr_before:.4f}</b>&nbsp;&nbsp;"
            f"α = <b>{alpha_before}</b></div>",
            unsafe_allow_html=True,
        )

    retrain_help = (
        "Retrains the GNN with your human feedback applied as a loss mask. "
        "Whitelisted devices are excluded from training loss so the model "
        "stops flagging them. Alpha is re-optimized via grid search."
    )
    if not has_feedback:
        st.caption("💡 Review at least one AI prediction above to enable retraining.")

    retrain_btn = st.button(
        "🔄 Retrain Model with Feedback",
        type="primary",
        use_container_width=True,
        disabled=not has_feedback,
        help=retrain_help,
    )

    if retrain_btn:
        import subprocess as _sp
        import sys as _sys
        import time as _time

        python_exe = _sys.executable
        log_placeholder = st.empty()
        log_lines = []

        def _run_step(label: str, cmd: str):
            log_lines.append(f"\n▶ {label}...")
            log_placeholder.code("\n".join(log_lines), language="") 
            proc = _sp.Popen(
                cmd, shell=True,
                stdout=_sp.PIPE, stderr=_sp.STDOUT,
                text=True, encoding="utf-8", errors="replace"
            )
            for line in proc.stdout:
                stripped = line.rstrip()
                if stripped:
                    log_lines.append(f"  {stripped}")
                    # Keep last 40 lines visible to avoid overflow
                    visible = log_lines[-40:]
                    log_placeholder.code("\n".join(visible), language="")
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"{label} failed (exit {proc.returncode})")
            log_lines.append(f"  ✓ {label} complete.")
            log_placeholder.code("\n".join(log_lines[-40:]), language="")

        try:
            env_prefix = f'cmd /c "set PYTHONPATH=. && "{python_exe}"'
            _run_step("Extracting features",
                      f'{env_prefix} src/data_pipeline/extract_features.py"')
            _run_step("Training DOMINANT (with alpha grid search)",
                      f'{env_prefix} src/data_pipeline/train.py"')
            _run_step("Running inference & updating graph",
                      f'{env_prefix} src/data_pipeline/predict.py"')

            # Reload model health metrics
            load_model_health.clear()
            load_topology_data.clear()
            meta_after = load_model_health()
            pr_after   = meta_after.get('pr_auc', None) if meta_after else None
            alpha_after = meta_after.get('alpha', None) if meta_after else None

            log_lines.append("\n" + "─" * 50)
            log_lines.append("  RETRAIN COMPLETE")
            if pr_before is not None and pr_after is not None:
                delta = pr_after - pr_before
                sign  = '+' if delta >= 0 else ''
                log_lines.append(f"  PR-AUC: {pr_before:.4f} → {pr_after:.4f}  ({sign}{delta:.4f})")
                log_lines.append(f"  Best α: {alpha_before} → {alpha_after}")
            log_lines.append("─" * 50)
            log_placeholder.code("\n".join(log_lines[-40:]), language="")

            if pr_after is not None and pr_before is not None:
                delta = pr_after - pr_before
                if delta >= 0:
                    st.success(f"✅ Retrain complete! PR-AUC improved by +{delta:.4f} → {pr_after:.4f}")
                else:
                    st.warning(f"⚠️ Retrain complete. PR-AUC changed by {delta:.4f} → {pr_after:.4f}")
            else:
                st.success("✅ Retrain complete! Refresh the page to see updated predictions.")

            _time.sleep(1.5)
            st.rerun()

        except Exception as e:
            st.error(f"❌ Retraining failed: {e}")



    if connected_devices:
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:11px; color:#8e99aa; font-weight:600; "
            "text-transform:uppercase; letter-spacing:0.5px; "
            "margin-bottom:6px;'>Connected Devices</div>",
            unsafe_allow_html=True,
        )
        for peer in connected_devices:
            peer_node = next(
                (n for n in topo.get("nodes", []) if n["id"] == peer), {}
            )
            peer_layer = peer_node.get("_layer", 2)
            peer_color = _NODE_COLORS.get(peer_layer, "#1e88e5")
            st.markdown(
                f"<div style='display:flex; align-items:center; gap:8px; "
                f"padding:4px 0; font-size:12px; color:#1a2535;'>"
                f"<div style='width:8px; height:8px; border-radius:50%; "
                f"background:{peer_color};'></div>{peer}</div>",
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# ── RAG CHATBOT ───────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _render_rag_chat():
    st.markdown(
        "<div style='font-size:13px; font-weight:700; color:#1a2535; "
        "margin-bottom:10px;'>🤖 Network RAG Assistant</div>",
        unsafe_allow_html=True,
    )

    # Init RAG (cached)
    rag_ready  = True
    rag_error  = ""
    try:
        driver      = get_neo4j_driver()
        embedder    = get_embedder()
        parser      = get_query_parser()
        retriever   = get_retriever(driver, embedder)
        synthesizer = get_synthesizer()
    except Exception as exc:
        rag_ready = False
        rag_error = str(exc)

    # Status indicator
    status_color = "#2e7d32" if rag_ready else "#c62828"
    status_label = "Neo4j Connected" if rag_ready else "Neo4j Unavailable"
    st.markdown(
        f"<div style='font-size:11px; color:{status_color}; font-weight:600; "
        f"margin-bottom:8px;'>● {status_label}</div>",
        unsafe_allow_html=True,
    )

    # Chat messages
    chat_box = st.container(height=340)
    with chat_box:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Input
    user_prompt = st.chat_input(
        "Ask about the network (e.g. 'List SPOF devices'…)", key="rag_input"
    )
    
    # Programmatic trigger from Device Details buttons
    if st.session_state.get("trigger_chat"):
        user_prompt = st.session_state.pop("trigger_chat")

    if user_prompt:
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with chat_box:
            with st.chat_message("user"):
                st.markdown(user_prompt)

        with chat_box:
            with st.chat_message("assistant"):
                if not rag_ready:
                    st.error(f"RAG engine unavailable: {rag_error}")
                else:
                    with st.spinner("Analysing…"):
                        try:
                            parsed   = parser.parse(user_prompt)
                            results  = retriever.retrieve(parsed)
                            
                            # Pre-append empty message to save partial stream
                            st.session_state.messages.append({"role": "assistant", "content": ""})
                            msg_idx = len(st.session_state.messages) - 1
                            
                            def stream_and_save():
                                for chunk in synthesizer.synthesize_stream(user_prompt, results):
                                    st.session_state.messages[msg_idx]["content"] += chunk
                                    yield chunk
                                    
                            st.write_stream(stream_and_save())
                            if results:
                                with st.expander("🔍 Retrieved context", expanded=False):
                                    for res in results:
                                        st.write(
                                            f"**Intent:** `{res.intent.type}` / `{res.intent.target}`"
                                        )
                                        txt = res.context_text
                                        st.text(txt[:500] + ("…" if len(txt) > 500 else ""))
                        except Exception as e:
                            err = f"❌ Error: {e}"
                            st.error(err)
                            st.session_state.messages.append(
                                {"role": "assistant", "content": err}
                            )


# ─────────────────────────────────────────────────────────────────────────────
# ── MAIN DASHBOARD ────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _render_dashboard():
    # Load topology data (cached 30s)
    topo = load_topology_data()

    # Sidebar — returns active filters
    filters = _render_sidebar(topo)

    # ── Header ──────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style='display:flex; align-items:center; gap:12px; margin-bottom:4px;'>
          <span style='font-size:22px;'>🔗</span>
          <div>
            <h2 style='margin:0; font-size:1.25rem; font-weight:700; color:#1a2535;'>
              Network Knowledge Graph Explorer
            </h2>
            <p style='margin:0; font-size:11.5px; color:#5a6474;'>
              NetGraphX — Real-time hierarchical topology with AI-powered insights
            </p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Metrics row ──────────────────────────────────────────────────────
    _render_metrics(topo)

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    # ── Topology graph (full width) ───────────────────────────────────
    view_label = filters.get("view", "Full Topology")
    node_count = len(_apply_filters(topo, filters)[0]) if topo else 0
    st.markdown(
        f"<div style='font-size:13px; font-weight:700; color:#1a2535; "
        f"margin-bottom:6px;'>🗺️ {view_label} "
        f"<span style='font-size:11px; color:#5a6474; font-weight:400;'>"
        f"({node_count} devices shown)</span></div>",
        unsafe_allow_html=True,
    )

    _render_graph(topo, filters)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Bottom panels: Device Details | RAG Chat ──────────────────────
    col_device, col_chat = st.columns([2, 3])

    with col_device:
        _render_device_details(topo)

    with col_chat:
        _render_rag_chat()


# ─────────────────────────────────────────────────────────────────────────────
# ── UTILITIES ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _fmt_utc(utc_str: Optional[str]) -> str:
    if not utc_str:
        return "—"
    try:
        dt = datetime.fromisoformat(utc_str)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return utc_str


# ─────────────────────────────────────────────────────────────────────────────
# ── ENTRYPOINT ────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def main():
    _init_session()
    if not st.session_state.authenticated:
        _render_login()
    else:
        page = st.session_state.get("current_page", "dashboard")
        if page == "dashboard":
            _render_dashboard()
        elif page == "rule_editor":
            from src.ui.rule_editor import render_rule_editor_page
            render_rule_editor_page()


if __name__ == "__main__":
    main()
