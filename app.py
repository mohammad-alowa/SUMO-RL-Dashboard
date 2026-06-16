"""Streamlit app for the Smart Traffic Light Management System."""
from __future__ import annotations

import datetime as dt
import threading
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from auth import authenticate_user, init_database, validate_email_domain
from rl_agent import QLearningAgent
from sumo_runner import run_simulation

st.set_page_config(page_title="Traffic Light Management System", layout="wide")
init_database()


def init_state() -> None:
    defaults = {
        "authenticated": False,
        "user": None,
        "simulation_started": False,
        "sumo_thread": None,
        "data_lock": threading.Lock(),
        "agent": QLearningAgent(),
        "shared_data": {
            "running": False,
            "step": 0,
            "queue_data": [],
            "waiting_time_data": [],
            "reward_data": [],
            "phase_data": [],
            "q_table_size": 0,
            "q_table_snapshot": [],
            "cumulative_reward": 0,
            "cumulative_waiting_time": 0,
            "last_update": None,
            "emergency_override": False,
            "error": None,
        },
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def page_style() -> None:
    st.markdown(
        """
        <style>
            .stButton>button {width: 100%; font-weight: 700; border-radius: 8px;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_login() -> None:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🚦 Traffic Management System")
        st.subheader("Administrator Login")
        with st.form("login_form"):
            email = st.text_input("Email Address", placeholder="name@moi.gov.sa")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

            if submitted:
                if not email or not password:
                    st.warning("Please enter both email and password")
                elif not validate_email_domain(email):
                    st.error("Email must be from @moi.gov.sa domain")
                else:
                    user, error = authenticate_user(email, password)
                    if user:
                        st.session_state.authenticated = True
                        st.session_state.user = user
                        st.success(f"Welcome, {user['full_name']}!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(error)


def get_data() -> dict:
    with st.session_state.data_lock:
        return dict(st.session_state.shared_data)


def reset_simulation_data() -> None:
    with st.session_state.data_lock:
        st.session_state.shared_data.update({
            "running": True,
            "step": 0,
            "queue_data": [],
            "waiting_time_data": [],
            "reward_data": [],
            "phase_data": [],
            "q_table_size": 0,
            "q_table_snapshot": [],
            "cumulative_reward": 0,
            "cumulative_waiting_time": 0,
            "last_update": None,
            "error": None,
        })


def render_sidebar(data: dict) -> None:
    st.sidebar.write(f"Logged in as: **{st.session_state.user['full_name']}**")
    if st.sidebar.button("Logout"):
        st.session_state.authenticated = False
        st.session_state.user = None
        st.rerun()

    st.sidebar.divider()
    st.sidebar.header("Simulation Control")

    if data.get("error"):
        st.sidebar.error(data["error"])

    if not st.session_state.simulation_started:
        total_steps = st.sidebar.number_input("Total Simulation Steps", min_value=1000, max_value=50000, value=10000, step=1000)
        if st.sidebar.button("Start Simulation", type="primary"):
            reset_simulation_data()
            st.session_state.simulation_started = True
            st.session_state.sumo_thread = threading.Thread(
                target=run_simulation,
                args=(st.session_state.shared_data, st.session_state.data_lock, st.session_state.agent, int(total_steps)),
                daemon=True,
            )
            st.session_state.sumo_thread.start()
            st.rerun()
    else:
        if st.sidebar.button("Stop Simulation"):
            with st.session_state.data_lock:
                st.session_state.shared_data["running"] = False
            st.session_state.simulation_started = False
            st.rerun()

    st.sidebar.divider()
    st.sidebar.header("RL Settings")
    agent = st.session_state.agent
    agent.alpha = st.sidebar.slider("Learning Rate (α)", 0.01, 1.00, float(agent.alpha), 0.01)
    agent.gamma = st.sidebar.slider("Discount Factor (γ)", 0.10, 1.00, float(agent.gamma), 0.01)
    agent.epsilon = st.sidebar.slider("Exploration Rate (ε)", 0.00, 1.00, float(agent.epsilon), 0.01)
    agent.min_green_steps = st.sidebar.slider("Min Green Steps", 50, 200, int(agent.min_green_steps), 10)


def render_dashboard_tab(data: dict) -> None:
    if data["queue_data"]:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Cumulative Reward", f"{data['cumulative_reward']:.0f}")
        col2.metric("Total Waiting Time", str(dt.timedelta(seconds=int(data['cumulative_waiting_time']))))
        col3.metric("Current Phase", data["phase_data"][-1]["phase"] if data["phase_data"] else 0)
        col4.metric("Current Total Queue", int(data["queue_data"][-1]["total_queue"]))

        df_queue = pd.DataFrame(data["queue_data"])
        st.subheader("Recent Queue Data")
        st.dataframe(df_queue.tail(20), use_container_width=True)

        st.plotly_chart(px.line(df_queue, x="step", y="total_queue", title="Total Queue Length Over Time"), use_container_width=True)
        lane_cols = ["q_EB_0", "q_EB_1", "q_EB_2", "q_SB_0", "q_SB_1", "q_SB_2"]
        st.plotly_chart(px.line(df_queue, x="step", y=lane_cols, title="Individual Lane Queue Lengths"), use_container_width=True)

        if data["reward_data"]:
            st.plotly_chart(px.line(pd.DataFrame(data["reward_data"]), x="step", y="reward", title="Cumulative Reward"), use_container_width=True)
        if data["waiting_time_data"]:
            df_wait = pd.DataFrame(data["waiting_time_data"])
            st.plotly_chart(px.line(df_wait, x="step", y="total_waiting", title="Total Waiting Time"), use_container_width=True)
    else:
        st.info("Start the simulation from the sidebar to see live data.")


def render_controls_tab(data: dict) -> None:
    st.info("Manual and emergency controls pause the RL agent until normal control is resumed.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Activate Emergency Override", type="primary"):
            with st.session_state.data_lock:
                st.session_state.shared_data["emergency_override"] = True
            st.success("Emergency override activated.")
    with col2:
        if st.button("Resume RL Agent"):
            with st.session_state.data_lock:
                st.session_state.shared_data["emergency_override"] = False
            st.success("RL agent resumed.")

    if data.get("emergency_override"):
        st.error("🚨 Emergency/manual mode active")
    else:
        st.success("Automatic mode active")


def render_settings_tab(data: dict) -> None:
    agent = st.session_state.agent
    col1, col2 = st.columns(2)
    col1.metric("Learning Rate (α)", f"{agent.alpha:.2f}")
    col1.metric("Discount Factor (γ)", f"{agent.gamma:.2f}")
    col2.metric("Exploration Rate (ε)", f"{agent.epsilon:.2f}")
    col2.metric("Min Green Steps", agent.min_green_steps)

    st.subheader("Q-Table")
    st.metric("States Learned", data.get("q_table_size", 0))
    snapshot = data.get("q_table_snapshot", [])
    if snapshot:
        rows = []
        for state, q_values in snapshot:
            rows.append({
                "State": str(state),
                "Q(Keep)": float(q_values[0]),
                "Q(Switch)": float(q_values[1]),
                "Best Action": "Switch" if q_values[1] > q_values[0] else "Keep",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)


def render_app() -> None:
    data = get_data()
    render_sidebar(data)
    st.title("🚦 Smart Traffic Light Management Dashboard")

    if data.get("running"):
        st.success(f"Simulation running — step {data['step']}")
    elif data["queue_data"]:
        st.info(f"Simulation stopped/completed — last step {data['step']}")

    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "🎛️ Controls", "⚙️ Settings"])
    with tab1:
        render_dashboard_tab(data)
    with tab2:
        render_controls_tab(data)
    with tab3:
        render_settings_tab(data)

    thread_alive = st.session_state.sumo_thread is not None and st.session_state.sumo_thread.is_alive()
    if data.get("running") and thread_alive:
        time.sleep(1)
        st.rerun()


init_state()
page_style()
if st.session_state.authenticated:
    render_app()
else:
    render_login()
