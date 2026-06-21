import os
import json
import streamlit as st

RULES_PATH = "config/network_audit_rules.json"

def render_rule_editor_page():
    # Load initial draft if not present
    if "audit_rules_draft" not in st.session_state:
        if os.path.exists(RULES_PATH):
            with open(RULES_PATH, "r", encoding="utf-8") as f:
                st.session_state.audit_rules_draft = json.load(f)
        else:
            st.session_state.audit_rules_draft = {}

    draft = st.session_state.audit_rules_draft

    # Callbacks to update draft
    def update_val(path, key):
        d = draft
        for p in path[:-1]:
            d = d[p]
        d[path[-1]] = st.session_state[key]

    def update_list(path, key):
        d = draft
        for p in path[:-1]:
            d = d[p]
        val_str = st.session_state[key]
        d[path[-1]] = [x.strip() for x in val_str.split(",") if x.strip()]

    def update_metric(path, key, orig_type):
        d = draft
        for p in path[:-1]:
            d = d[p]
        val = st.session_state[key]
        if orig_type is bool:
            d[path[-1]] = bool(val)
        elif orig_type is int:
            try:
                d[path[-1]] = int(val)
            except ValueError:
                pass # Keep as string if invalid
        elif orig_type is float:
            try:
                d[path[-1]] = float(val)
            except ValueError:
                pass
        else:
            d[path[-1]] = val

    # ---- CSS Tweaks for Form Look ----
    st.markdown("""
        <style>
        .rule-editor-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 1rem;
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: 2rem;
        }
        .rule-panel {
            background-color: #f8f9fa;
            padding: 1.5rem;
            border-radius: 8px;
            border: 1px solid #e0e0e0;
            margin-bottom: 1.5rem;
        }
        .rule-panel h4 {
            margin-top: 0;
            color: #1a2535;
        }
        </style>
    """, unsafe_allow_html=True)

    # ---- Header ----
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown("<h2 style='margin:0;'>Network Topology Audit Rule Editor</h2>", unsafe_allow_html=True)
    with col2:
        if st.button("⬅️ Back to Dashboard", use_container_width=True):
            if "audit_rules_draft" in st.session_state:
                del st.session_state["audit_rules_draft"]
            st.session_state.current_page = "dashboard"
            st.rerun()

    st.markdown("<hr style='margin-top:0.5rem; margin-bottom:1.5rem;'>", unsafe_allow_html=True)

    # ---- Sidebar Navigation ----
    with st.sidebar:
        st.markdown("### Rule Configuration")
        
        # Build dynamic options from draft keys
        rule_keys = [k for k in draft.keys() if k != "global"]
        options = ["Global Settings"]
        key_map = {}
        for rk in rule_keys:
            rname = draft[rk].get("rule_name", rk)
            # Ensure unique names for radio options
            if rname in key_map:
                rname = f"{rname} ({rk})"
            options.append(rname)
            key_map[rname] = rk
            
        selection = st.radio(
            "Sections",
            options=options,
            label_visibility="collapsed"
        )
        
        st.markdown("---")
        with st.expander("➕ Add New Rule"):
            new_id = st.text_input("Rule ID (e.g. bgp_check)", key="new_rule_id_input")
            if st.button("Add", use_container_width=True):
                if new_id and new_id not in draft and new_id != "global":
                    draft[new_id] = {
                        "rule_id": new_id,
                        "rule_name": f"New Rule: {new_id}",
                        "compliance_status": {"pass": "compliant", "fail": f"non_compliant_{new_id}"},
                        "global_summary": {"pass": "", "fail": ""},
                        "node_knowledge_template": {"pass": "", "fail": ""},
                        "metrics": {}
                    }
                    st.rerun()
        
        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            with open(RULES_PATH, "w", encoding="utf-8") as f:
                json.dump(draft, f, indent=2, ensure_ascii=False)
            st.success("✅ Rules saved successfully!")
            
        if st.button("❌ Discard Changes", use_container_width=True):
            if "audit_rules_draft" in st.session_state:
                del st.session_state["audit_rules_draft"]
            st.rerun()

    # ---- Main Content Area ----
    if selection == "Global Settings":
        st.markdown("### Global Settings Panel (Active)")
        glob = draft.get("global", {})
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='rule-panel'>", unsafe_allow_html=True)
            st.markdown("#### Global Rule Behavior")
            
            k = "glob_version"
            st.text_input("config_version", value=glob.get("config_version", ""), key=k, on_change=update_val, args=(["global", "config_version"], k))
            
            k = "glob_default_status"
            st.text_input("default_compliance_status", value=glob.get("default_compliance_status", ""), key=k, on_change=update_val, args=(["global", "default_compliance_status"], k))
            
            k = "glob_status_priority"
            priority_str = ", ".join(glob.get("compliance_status_priority", []))
            st.text_area("compliance_status_priority (comma separated)", value=priority_str, height=140, key=k, on_change=update_list, args=(["global", "compliance_status_priority"], k))
            st.markdown("</div>", unsafe_allow_html=True)

        with c2:
            st.markdown("<div class='rule-panel'>", unsafe_allow_html=True)
            st.markdown("#### Merged Compliance Templates")
            merged = glob.get("merged_compliance", {})
            
            k = "glob_pass_tmpl"
            st.text_area("pass_knowledge_template", value=merged.get("pass_knowledge_template", ""), height=100, key=k, on_change=update_val, args=(["global", "merged_compliance", "pass_knowledge_template"], k))
            
            k = "glob_pass_sum"
            st.text_area("global_pass_summary", value=merged.get("global_pass_summary", ""), height=80, key=k, on_change=update_val, args=(["global", "merged_compliance", "global_pass_summary"], k))
            
            k = "glob_fail_sum"
            st.text_area("global_fail_summary", value=merged.get("global_fail_summary", ""), height=80, key=k, on_change=update_val, args=(["global", "merged_compliance", "global_fail_summary"], k))
            st.markdown("</div>", unsafe_allow_html=True)

    else:
        rkey = key_map[selection]
        rule = draft.get(rkey, {})
        
        col_title, col_del = st.columns([4, 1])
        with col_title:
            st.markdown(f"### Rule: {rule.get('rule_name', selection)}")
        with col_del:
            if st.button("🗑️ Delete Rule", use_container_width=True):
                del draft[rkey]
                st.rerun()
        
        st.markdown("<div class='rule-panel'>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("rule_id", value=rule.get("rule_id", ""), disabled=True)
        with c2:
            k = f"{rkey}_rule_name"
            st.text_input("rule_name", value=rule.get("rule_name", ""), key=k, on_change=update_val, args=([rkey, "rule_name"], k))
            
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("<br><b>Compliance Status</b>", unsafe_allow_html=True)
            cs = rule.get("compliance_status", {})
            k1 = f"{rkey}_cs_pass"
            st.text_input("Pass", value=cs.get("pass", ""), key=k1, on_change=update_val, args=([rkey, "compliance_status", "pass"], k1))
        with c4:
            st.markdown("<br><b>&nbsp;</b>", unsafe_allow_html=True)
            k2 = f"{rkey}_cs_fail"
            st.text_input("Fail", value=cs.get("fail", ""), key=k2, on_change=update_val, args=([rkey, "compliance_status", "fail"], k2))
            
        st.markdown("<br><b>Global Summary</b>", unsafe_allow_html=True)
        gs = rule.get("global_summary", {})
        k3 = f"{rkey}_gs_pass"
        st.text_area("Pass Summary", value=gs.get("pass", ""), height=80, key=k3, on_change=update_val, args=([rkey, "global_summary", "pass"], k3))
        k4 = f"{rkey}_gs_fail"
        st.text_area("Fail Summary", value=gs.get("fail", ""), height=80, key=k4, on_change=update_val, args=([rkey, "global_summary", "fail"], k4))
        st.markdown("</div>", unsafe_allow_html=True)
        
        c_left, c_right = st.columns(2)
        with c_left:
            st.markdown("<div class='rule-panel'>", unsafe_allow_html=True)
            st.markdown("#### Node Knowledge Templates")
            nkt = rule.get("node_knowledge_template", {})
            for nk, nv in nkt.items():
                kk = f"{rkey}_nkt_{nk}"
                st.text_area(f"{nk.capitalize()} Template", value=nv, height=100, key=kk, on_change=update_val, args=([rkey, "node_knowledge_template", nk], kk))
                
            if "link_knowledge_template" in rule:
                kk = f"{rkey}_lkt"
                st.text_area("Link Knowledge Template", value=rule["link_knowledge_template"], height=100, key=kk, on_change=update_val, args=([rkey, "link_knowledge_template"], kk))
            st.markdown("</div>", unsafe_allow_html=True)

        with c_right:
            st.markdown("<div class='rule-panel'>", unsafe_allow_html=True)
            st.markdown("#### Metrics")
            metrics = rule.get("metrics", {})
            if not metrics:
                st.info("No metrics configured for this rule.")
            else:
                for mk, mv in metrics.items():
                    kk = f"{rkey}_met_{mk}"
                    orig_type = type(mv)
                    if orig_type is bool:
                        st.checkbox(mk, value=mv, key=kk, on_change=update_metric, args=([rkey, "metrics", mk], kk, orig_type))
                    else:
                        st.text_input(mk, value=str(mv), key=kk, on_change=update_metric, args=([rkey, "metrics", mk], kk, orig_type))
            st.markdown("</div>", unsafe_allow_html=True)
