from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import streamlit as st

from planner_service import run_trip
from travel_planner.sandbox import SANDBOX_ROOT
from travel_planner.schemas import TravelRequest
from travel_planner.skills import AGENT_SKILLS


st.set_page_config(
    page_title="Atlas // Travel Intelligence",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');
    :root { --ink:#24211d; --muted:#77736c; --line:#e6e1d8; --cream:#faf9f6; --paper:#f3f1ec; --clay:#c96b4b; --sage:#dfe8dc; --dark:#292824; }
    .stApp { background:var(--paper); color:var(--ink); }
    [data-testid="stSidebar"] { background:var(--dark); border-right:1px solid #3c3a35; }
    [data-testid="stSidebar"] * { color:#f1eee7 !important; }
    [data-testid="stSidebar"] .stCaption { color:#aaa69d !important; }
    [data-testid="stSidebar"] [data-testid="stExpander"] { background:#312f2b; border:1px solid #46433d; }
    h1,h2,h3 { font-family:'DM Sans', sans-serif; letter-spacing:0; }
    h1 { font-size:2.55rem !important; line-height:1.02 !important; }
    h2 { font-size:1.3rem !important; margin-top:1.2rem !important; }
    p, label, .stMarkdown { font-family:'DM Sans', sans-serif; }
    .mono { font-family:'Space Mono', monospace; font-size:.72rem; letter-spacing:.04em; color:var(--muted); text-transform:uppercase; }
    .hero { padding:2.4rem 0 1.2rem; margin-bottom:.8rem; }
    .hero-kicker { color:var(--clay); font-family:'Space Mono',monospace; font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; margin-bottom:.8rem; }
    .hero-copy { color:var(--muted); max-width:680px; font-size:1rem; }
    .workspace-label { color:var(--muted); font-size:.78rem; margin:1.5rem 0 .55rem; }
    .welcome { background:var(--cream); border:1px solid var(--line); padding:1.25rem 1.4rem; margin:.7rem 0 1rem; }
    .welcome-title { font-size:1.1rem; font-weight:700; margin-bottom:.35rem; }
    .welcome-copy { color:var(--muted); font-size:.9rem; }
    .composer { background:var(--cream); border:1px solid var(--line); padding:1.2rem; margin-top:1rem; }
    .composer-title { font-size:.82rem; font-weight:700; letter-spacing:.02em; margin-bottom:.7rem; }
    .rail-heading { font-family:'DM Sans', sans-serif; font-weight:700; font-size:.95rem; margin:1.3rem 0 .45rem; }
    .skill-row { border-bottom:1px solid #45423c; padding:.55rem 0; }
    .skill-name { font-size:.82rem; font-weight:700; }
    .skill-detail { color:#aaa69d; font-size:.7rem; line-height:1.35; margin-top:.15rem; }
    .sandbox-path { color:#d7a36c; font-family:'Space Mono',monospace; font-size:.67rem; overflow-wrap:anywhere; }
    .metric { background:var(--cream); border:1px solid var(--line); padding:1rem; min-height:105px; }
    .metric-value { font-family:'Space Mono',monospace; font-size:1.65rem; color:var(--green); margin-top:.35rem; }
    .metric-label { color:var(--muted); font-size:.8rem; }
    .agent { background:var(--cream); border:1px solid var(--line); border-left:4px solid var(--clay); padding:.8rem 1rem; margin:.45rem 0; }
    .agent-title { font-weight:700; }
    .agent-detail { color:var(--muted); font-size:.82rem; }
    .status-pill { display:inline-block; background:var(--sage); color:#3d624b; padding:.25rem .55rem; font-family:'Space Mono',monospace; font-size:.68rem; text-transform:uppercase; }
    .stButton > button { border-radius:3px; font-weight:700; min-height:2.7rem; }
    div[data-testid="stForm"] { background:var(--cream); border:1px solid var(--line); padding:1.2rem; }
    div[data-testid="stExpander"] { border-color:var(--line); background:transparent; }
    .stButton > button[kind="primary"] { background:var(--clay); border-color:var(--clay); color:white; }
    </style>
    """,
    unsafe_allow_html=True,
)


def metric(label: str, value: str) -> None:
    st.markdown(
        f'<div class="metric"><div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div></div>',
        unsafe_allow_html=True,
    )


def render_agent_outputs(progress_events: list[tuple[str, dict]]) -> None:
    st.subheader("Every agent output")
    st.caption("The structured state returned by each planner, specialist, and review node.")
    if not progress_events:
        st.info("No agent output was recorded for this run.")
        return

    hidden_keys = {"execution_log", "resource_usage", "errors", "loop_trace"}
    for index, (node_name, update) in enumerate(progress_events, start=1):
        outputs = {key: value for key, value in update.items() if key not in hidden_keys}
        usage = update.get("resource_usage", [])
        logs = update.get("execution_log", [])
        label = node_name.replace("_", " ").title()
        with st.expander(f"{index:02d}  {label}", expanded=index == len(progress_events)):
            if outputs:
                for key, value in outputs.items():
                    st.markdown(f"**{key.replace('_', ' ').title()}**")
                    if isinstance(value, (dict, list)):
                        st.json(value, expanded=True)
                    else:
                        st.write(value)
            else:
                st.caption("This node returned execution metadata without a structured payload.")
            if logs:
                st.markdown("**Execution log**")
                for line in logs:
                    st.code(line)
            if usage:
                st.markdown("**Resource usage**")
                st.json(usage, expanded=False)


def render_run(result: dict, progress_events: list[tuple[str, dict]]) -> None:
    budget = result.get("budget_result", {})
    critique = result.get("critique_result", {})
    st.markdown('<div class="mono">RUN COMPLETE</div>', unsafe_allow_html=True)
    st.title("Trip intelligence, assembled.")
    st.markdown(
        '<div class="hero-copy">A traceable plan built from specialist agents, grounded references, and bounded model usage.</div>',
        unsafe_allow_html=True,
    )

    columns = st.columns(5)
    with columns[0]: metric("LLM calls", str(result.get("total_llm_calls", 0)))
    with columns[1]: metric("Tool calls", str(result.get("total_tool_calls", 0)))
    with columns[2]: metric("Tokens", f"{result.get('total_tokens', 0):,}")
    with columns[3]: metric("Budget", f"{budget.get('total', 0):,.0f} {result['request'].get('currency', '')}")
    with columns[4]: metric("Quality", str(critique.get("quality_score", "-")))

    st.markdown("## Agent activity")
    for node_name, update in progress_events:
        lines = update.get("execution_log", [])
        detail = lines[-1] if lines else "Completed"
        st.markdown(
            f'<div class="agent"><span class="status-pill">complete</span> '
            f'<span class="agent-title">{node_name.replace("_", " ").title()}</span>'
            f'<div class="agent-detail">{detail}</div></div>',
            unsafe_allow_html=True,
        )

    tabs = st.tabs(["Itinerary", "Agent outputs", "Budget", "Evidence & loops", "Run report"])
    with tabs[0]:
        st.markdown(result.get("final_plan", {}).get("travel_plan", "No itinerary generated."))
    with tabs[1]:
        render_agent_outputs(progress_events)
    with tabs[2]:
        left, right = st.columns([1.15, 1])
        with left:
            st.subheader("Cost allocation")
            rows = {key: budget.get(key, 0) for key in ["flight", "hotel", "food", "transport", "activities", "buffer"]}
            st.bar_chart(rows, horizontal=True)
        with right:
            st.subheader("Budget facts")
            st.json(budget, expanded=True)
    with tabs[3]:
        st.subheader("Loop trace")
        for item in result.get("loop_trace", []):
            st.markdown(f"- `{item}`")
        st.subheader("Specialists spawned")
        for item in result.get("subagents_spawned", []):
            st.markdown(f"- `{item['agent']}` · `{item['id']}` · {item['ts']}")
        st.subheader("Input references")
        for path in result["request"].get("reference_files", []):
            st.markdown(f"- `{Path(path).name}`")
    with tabs[4]:
        st.download_button("Download JSON report", json.dumps(result, indent=2, default=str), "run_report.json", "application/json")
        pdf_path = result.get("pdf_path")
        if pdf_path and Path(pdf_path).exists():
            st.download_button("Download PDF plan", Path(pdf_path).read_bytes(), "travel_plan.pdf", "application/pdf")
        st.json({
            "errors": result.get("errors", []),
            "warnings": result.get("input_warnings", []) + result.get("final_plan", {}).get("guardrail_warnings", []),
            "usage_by_agent": result.get("token_totals_by_agent", {}),
        }, expanded=False)


def render_workspace_sidebar() -> None:
    st.sidebar.markdown('<div class="mono">ATLAS / WORKSPACE</div>', unsafe_allow_html=True)
    st.sidebar.title("Travel planner")
    st.sidebar.caption("A focused planning workspace for grounded trip decisions.")
    st.sidebar.button("＋  New trip", use_container_width=True, type="primary")
    st.sidebar.markdown('<div class="rail-heading">Workspace</div>', unsafe_allow_html=True)
    st.sidebar.markdown("▸  Current trip")
    st.sidebar.caption("Untitled itinerary")

    with st.sidebar.expander("✦  Skills", expanded=True):
        st.caption("Specialists available to this workspace")
        for skill in AGENT_SKILLS.values():
            st.markdown(
                f'<div class="skill-row"><div class="skill-name">{skill.name}</div>'
                f'<div class="skill-detail">{skill.objective}</div></div>',
                unsafe_allow_html=True,
            )

    with st.sidebar.expander("⌁  Sandbox", expanded=True):
        st.caption("Private working directory")
        st.markdown(f'<div class="sandbox-path">{SANDBOX_ROOT}</div>', unsafe_allow_html=True)
        sandbox_files = sorted(path.name for path in SANDBOX_ROOT.iterdir() if path.is_file())
        if sandbox_files:
            for name in sandbox_files[:8]:
                st.markdown(f"`{name}`")
        else:
            st.caption("No files yet. Generated artifacts will appear here.")

    st.sidebar.divider()
    st.sidebar.markdown('<div class="mono">SYSTEM POSTURE</div>', unsafe_allow_html=True)
    st.sidebar.markdown("`CACHE FIRST`  ·  `TRACE ON`  ·  `GUARDRAILS ON`")


def main() -> None:
    render_workspace_sidebar()

    st.markdown(
        '<div class="hero"><div class="hero-kicker">Atlas / planning workspace</div>'
        '<h1>Where should we go?</h1>'
        '<div class="hero-copy">Tell Atlas what kind of trip you have in mind. Your research skills will gather the details, keep the budget visible, and leave a trail you can inspect.</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="welcome"><div class="welcome-title">Plan a thoughtful trip</div>'
        '<div class="welcome-copy">Start with a destination, a budget, and a few preferences. Add reference files when you want the planner to work from your own material.</div></div>',
        unsafe_allow_html=True,
    )

    with st.expander("Trip brief", expanded=True):
        st.markdown('<div class="composer-title">Describe the trip you want to make</div>', unsafe_allow_html=True)
        with st.form("trip_setup"):
            st.markdown('<div class="mono">01 / Trip brief</div>', unsafe_allow_html=True)
            first, second = st.columns(2)
            with first:
                origin = st.text_input("Origin", "Delhi")
                destination = st.text_input("Destination", "Vadodara")
                budget = st.number_input("Total budget", min_value=1.0, value=40000.0, step=1000.0)
                currency = st.selectbox("Currency", ["INR", "USD", "EUR", "GBP"], index=0)
            with second:
                days = st.number_input("Days", min_value=1, max_value=30, value=3)
                travelers = st.number_input("Travelers", min_value=1, max_value=20, value=2)
                style = st.selectbox("Travel style", ["budget", "balanced", "premium"], index=1)
                hotel = st.selectbox("Hotel preference", ["budget", "comfortable", "premium"], index=1)
            food = st.selectbox("Food preference", ["local", "mixed", "vegetarian", "premium"], index=1)
            interests = st.text_input("Interests", "history, museums, local food, malls")
            notes = st.text_area("Constraints and notes", "Prefer vegetarian food options and at least one half-day dedicated to museums.")
            uploads = st.file_uploader("Reference files", type=["txt", "md", "csv", "pdf", "docx", "xlsx", "xlsm"], accept_multiple_files=True)
            fresh = st.checkbox("Live research mode", value=False, help="Bypass caches and call the live search/model services.")
            submitted = st.form_submit_button("Run planning system", type="primary", use_container_width=True)

    if submitted:
        if not origin.strip() or not destination.strip():
            st.error("Origin and destination are required.")
            return
        reference_paths: list[str] = []
        upload_dir = Path(tempfile.mkdtemp(prefix="atlas-references-"))
        for upload in uploads or []:
            path = upload_dir / upload.name
            path.write_bytes(upload.getbuffer())
            reference_paths.append(str(path))
        request = TravelRequest(
            origin=origin,
            destination=destination,
            total_budget=budget,
            currency=currency,
            travelers=int(travelers),
            days=int(days),
            travel_style=style,
            hotel_preference=hotel,
            food_preference=food,
            interests=[item.strip() for item in interests.split(",") if item.strip()],
            notes=notes,
            reference_files=reference_paths,
        )
        progress_events: list[tuple[str, dict]] = []
        status = st.status("Running planning system...", expanded=True)
        status.write("Orchestrator is reading the brief and references.")

        def on_progress(node_name: str, update: dict) -> None:
            progress_events.append((node_name, update))
            status.write(f"Completed {node_name.replace('_', ' ')}")

        try:
            result = run_trip(request, force_refresh=fresh, progress=on_progress)
            status.update(label="Planning system complete", state="complete", expanded=False)
            st.session_state["result"] = result
            st.session_state["progress_events"] = progress_events
        except Exception as exc:
            status.update(label="Planning system stopped", state="error")
            st.exception(exc)

    if st.session_state.get("result"):
        st.divider()
        render_run(st.session_state["result"], st.session_state.get("progress_events", []))


if __name__ == "__main__":
    main()
