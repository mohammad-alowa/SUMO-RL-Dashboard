import streamlit as st
import sqlite3
import bcrypt
import time

# =============================================================================
# DATABASE SETUP
# =============================================================================

def init_database():
    """Initialize database with first admin account"""
    conn = sqlite3.connect('traffic_system.db', check_same_thread=False)
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    )''')
    
    conn.commit()
    
    # Create default admin if none exists
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        # Default credentials
        default_email = "traffic@moi.gov.sa"
        default_password = "Admin@2025"
        default_name = "Traffic Administrator"
        
        password_hash = bcrypt.hashpw(default_password.encode('utf-8'), bcrypt.gensalt())
        
        c.execute('''INSERT INTO users (email, password_hash, full_name) 
                     VALUES (?, ?, ?)''',
                  (default_email, password_hash, default_name))
        conn.commit()
        
        print("=" * 70)
        print("DEFAULT ADMIN ACCOUNT CREATED")
        print("=" * 70)
        print(f"Email: {default_email}")
        print(f"Password: {default_password}")
        print("=" * 70)
    
    conn.close()

def validate_email_domain(email):
    """Only allow @moi.gov.sa emails"""
    if not email or '@' not in email:
        return False
    
    domain = email.split('@')[1].lower()
    return domain == 'moi.gov.sa'

def authenticate_user(email, password):
    """Authenticate user"""
    import datetime
    
    conn = sqlite3.connect('traffic_system.db', check_same_thread=False)
    c = conn.cursor()
    
    # Parameterized query prevents SQL injection
    c.execute('SELECT id, email, password_hash, full_name FROM users WHERE email = ?', 
              (email,))
    user = c.fetchone()
    
    if not user:
        conn.close()
        return None, "Invalid email or password"
    
    user_id, email, password_hash, full_name = user
    
    # Verify password with bcrypt
    if bcrypt.checkpw(password.encode('utf-8'), password_hash):
        # Update last login
        c.execute('UPDATE users SET last_login = ? WHERE id = ?',
                  (datetime.datetime.now(), user_id))
        conn.commit()
        conn.close()
        
        return {'id': user_id, 'email': email, 'full_name': full_name}, None
    else:
        conn.close()
        return None, "Invalid email or password"

# Initialize database
init_database()

# =============================================================================
# SESSION STATE
# =============================================================================

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'user' not in st.session_state:
    st.session_state.user = None

# =============================================================================
# STREAMLIT UI - LOGIN PAGE
# =============================================================================

st.set_page_config(
    page_title="Traffic Management System - Login",
    layout="wide"
)

# Custom CSS - RED THEME
st.markdown("""
<style>
    .main {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    .stButton>button {
        width: 100%;
        background-color: #FF4B4B;
        color: white;
        font-weight: bold;
        padding: 12px;
        border-radius: 8px;
        border: none;
    }
    .stButton>button:hover {
        background-color: #FF6B6B;
    }
</style>
""", unsafe_allow_html=True)

# Check if already authenticated - redirect to dashboard
if st.session_state.authenticated:
    # Import the dashboard code and run it
    import pandas as pd
    import numpy as np
    import plotly.express as px
    import plotly.graph_objects as go
    import os
    import sys
    import threading
    from queue import Queue
    import datetime

    # SUMO Setup
    if 'SUMO_HOME' in os.environ:
        tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
        sys.path.append(tools)
    else:
        st.error("Please declare environment variable 'SUMO_HOME'")
        st.stop()

    import traci

    # Initialize session state for simulation
    if 'simulation_started' not in st.session_state:
        st.session_state.simulation_started = False
    if 'sumo_thread' not in st.session_state:
        st.session_state.sumo_thread = None
    if 'last_sync_time' not in st.session_state:
        st.session_state.last_sync_time = None

    # Store shared simulation data
    if 'shared_simulation_data' not in st.session_state:
        st.session_state.shared_simulation_data = {
            'running': False,
            'step': 0,
            'queue_data': [],
            'waiting_time_data': [],
            'reward_data': [],
            'phase_data': [],
            'q_table_size': 0,
            'cumulative_reward': 0,
            'cumulative_waiting_time': 0,
            'last_update': None,
            'q_table_snapshot': [],
            'emergency_override': False
        }

    # Message system for auto-clearing notifications
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    def add_message(msg_type, text, duration=3):
        """Add a temporary message that auto-clears after duration seconds"""
        import uuid
        st.session_state.messages = [{
            'id': str(uuid.uuid4()),
            'type': msg_type,
            'text': text,
            'timestamp': time.time(),
            'duration': duration
        }]
        if 'displayed_message_ids' not in st.session_state:
            st.session_state.displayed_message_ids = set()

    def show_messages():
        """Display active messages - only once per unique message"""
        current_time = time.time()
        
        if 'displayed_message_ids' not in st.session_state:
            st.session_state.displayed_message_ids = set()
        
        active_messages = [
            msg for msg in st.session_state.messages 
            if current_time - msg['timestamp'] < msg['duration']
        ]
        
        st.session_state.messages = active_messages
        
        for msg in active_messages:
            if msg['id'] not in st.session_state.displayed_message_ids:
                if msg['type'] == 'success':
                    st.success(msg['text'])
                elif msg['type'] == 'error':
                    st.error(msg['text'])
                elif msg['type'] == 'warning':
                    st.warning(msg['text'])
                elif msg['type'] == 'info':
                    st.info(msg['text'])
                st.session_state.displayed_message_ids.add(msg['id'])
        
        active_ids = {msg['id'] for msg in active_messages}
        st.session_state.displayed_message_ids = st.session_state.displayed_message_ids & active_ids

    shared_simulation_data = st.session_state.shared_simulation_data

    # Lock for thread-safe access
    if 'data_lock' not in st.session_state:
        st.session_state.data_lock = threading.Lock()
    data_lock = st.session_state.data_lock

    # Q-Learning parameters - STORED IN SESSION STATE
    if 'rl_params' not in st.session_state:
        st.session_state.rl_params = {
            'ALPHA': 0.1,
            'GAMMA': 0.9,
            'EPSILON': 0.1,
            'MIN_GREEN_STEPS': 100,
            'ACTIONS': [0, 1]
        }

    rl_params = st.session_state.rl_params

    Q_table = {}
    last_switch_step = -rl_params['MIN_GREEN_STEPS']

    # -------------------------
    # Q-Learning Functions
    # -------------------------

    def get_max_Q_value_of_state(s):
        if s not in Q_table:
            Q_table[s] = np.zeros(len(rl_params['ACTIONS']))
        return np.max(Q_table[s])

    def get_reward(state):
        total_queue = sum(state[:-1])
        reward = -float(total_queue)
        return reward

    def get_queue_length(detector_id):
        try:
            return traci.lanearea.getLastStepVehicleNumber(detector_id)
        except:
            return 0

    def get_waiting_time(detector_id):
        try:
            return traci.lane.getWaitingTime(detector_id)
        except:
            return 0

    def get_current_phase(tls_id):
        try:
            return traci.trafficlight.getPhase(tls_id)
        except:
            return 0

    def get_state():
        detector_Node1_2_EB_0 = "Node1_2_EB_0"
        detector_Node1_2_EB_1 = "Node1_2_EB_1"
        detector_Node1_2_EB_2 = "Node1_2_EB_2"
        
        detector_Node2_7_SB_0 = "Node2_7_SB_0"
        detector_Node2_7_SB_1 = "Node2_7_SB_1"
        detector_Node2_7_SB_2 = "Node2_7_SB_2"
        
        traffic_light_id = "Node2"
        
        q_EB_0 = get_queue_length(detector_Node1_2_EB_0)
        q_EB_1 = get_queue_length(detector_Node1_2_EB_1)
        q_EB_2 = get_queue_length(detector_Node1_2_EB_2)

        q_SB_0 = get_queue_length(detector_Node2_7_SB_0)
        q_SB_1 = get_queue_length(detector_Node2_7_SB_1)
        q_SB_2 = get_queue_length(detector_Node2_7_SB_2)

        wt_EB_0 = get_waiting_time(detector_Node1_2_EB_0)
        wt_EB_1 = get_waiting_time(detector_Node1_2_EB_1)
        wt_EB_2 = get_waiting_time(detector_Node1_2_EB_2)

        wt_SB_0 = get_waiting_time(detector_Node2_7_SB_0)
        wt_SB_1 = get_waiting_time(detector_Node2_7_SB_1)
        wt_SB_2 = get_waiting_time(detector_Node2_7_SB_2)

        current_phase = get_current_phase(traffic_light_id)

        return (q_EB_0, q_EB_1, q_EB_2, q_SB_0, q_SB_1, q_SB_2, 
                wt_EB_0, wt_EB_1, wt_EB_2, wt_SB_0, wt_SB_1, wt_SB_2, 
                current_phase)

    def get_action_from_policy(state):
        import random
        if random.random() < rl_params['EPSILON']:
            return random.choice(rl_params['ACTIONS'])
        else:
            if state not in Q_table:
                Q_table[state] = np.zeros(len(rl_params['ACTIONS']))
            return int(np.argmax(Q_table[state]))

    def apply_action(action, current_step, tls_id="Node2"):
        global last_switch_step
        
        with data_lock:
            if shared_simulation_data.get('emergency_override', False):
                return
        
        if action == 0:
            return
        
        elif action == 1:
            if current_step - last_switch_step >= rl_params['MIN_GREEN_STEPS']:
                try:
                    program = traci.trafficlight.getAllProgramLogics(tls_id)[0]
                    num_phases = len(program.phases)
                    next_phase = (get_current_phase(tls_id) + 1) % num_phases
                    traci.trafficlight.setPhase(tls_id, next_phase)
                    last_switch_step = current_step
                except:
                    pass

    def update_Q_table(old_state, action, reward, new_state):
        global Q_table
        if old_state not in Q_table:
            Q_table[old_state] = np.zeros(len(rl_params['ACTIONS']))
        
        old_q = Q_table[old_state][action]
        best_future_q = get_max_Q_value_of_state(new_state)
        Q_table[old_state][action] = old_q + rl_params['ALPHA'] * (reward + rl_params['GAMMA'] * best_future_q - old_q)
        
        if len(Q_table) % 50 == 0:
            try:
                with data_lock:
                    snapshot = []
                    for state, q_vals in list(Q_table.items())[-20:]:
                        snapshot.append((state, q_vals.copy()))
                    shared_simulation_data['q_table_snapshot'] = snapshot
            except:
                pass

    def detect_emergency_vehicle_direction(tls_id="Node2"):
        """Detect which direction emergency vehicle is approaching from"""
        try:
            all_vehicles = traci.vehicle.getIDList()
            
            emergency_vehicles = []
            for veh_id in all_vehicles:
                try:
                    veh_class = traci.vehicle.getVehicleClass(veh_id)
                    if veh_class == "emergency":
                        emergency_vehicles.append(veh_id)
                except:
                    continue
            
            if not emergency_vehicles:
                print("No emergency vehicles detected")
                return None
            
            for veh_id in emergency_vehicles:
                try:
                    edge_id = traci.vehicle.getRoadID(veh_id)
                    
                    if "Node1_2" in edge_id or "Node2_3" in edge_id:
                        print(f"Emergency vehicle {veh_id} detected on East-West corridor (edge: {edge_id})")
                        return "EW"
                    elif "Node2_7" in edge_id or "Node2_5" in edge_id:
                        print(f"Emergency vehicle {veh_id} detected on North-South corridor (edge: {edge_id})")
                        return "NS"
                except:
                    continue
            
            print(f"Emergency vehicle found but direction unclear")
            return None
            
        except Exception as e:
            print(f"Error detecting emergency vehicle: {str(e)}")
            return None

    def activate_emergency_smart(tls_id="Node2"):
        """Activate emergency by giving green to the direction with emergency vehicle"""
        try:
            with data_lock:
                shared_simulation_data['emergency_override'] = True
            
            direction = detect_emergency_vehicle_direction(tls_id)
            
            if direction == "EW":
                traci.trafficlight.setPhase(tls_id, 0)
                print(f"EMERGENCY: East-West GREEN at {tls_id} - RL agent paused")
                return True, "East-West"
            elif direction == "NS":
                traci.trafficlight.setPhase(tls_id, 2)
                print(f"EMERGENCY: North-South GREEN at {tls_id} - RL agent paused")
                return True, "North-South"
            else:
                print(f"EMERGENCY: Current state maintained (no vehicle detected) at {tls_id} - RL agent paused")
                return True, "Current state maintained"
                
        except Exception as e:
            print(f"ERROR activating emergency at {tls_id}: {str(e)}")
            return False, "Error"

    def activate_emergency_all_green(tls_id="Node2"):
        """Activate emergency by setting ALL directions to GREEN"""
        try:
            with data_lock:
                shared_simulation_data['emergency_override'] = True
            
            all_green_state = "GGGGGGGGGGGGGGGGGGGG"
            traci.trafficlight.setRedYellowGreenState(tls_id, all_green_state)
            print(f"EMERGENCY: All lights GREEN at {tls_id} - RL agent paused")
            return True
        except Exception as e:
            print(f"ERROR activating emergency at {tls_id}: {str(e)}")
            return False

    def set_traffic_light_phase(tls_id, phase_name):
        """Manually set traffic light phase from dashboard"""
        try:
            with data_lock:
                shared_simulation_data['emergency_override'] = True
            
            if phase_name == 'Green':
                traci.trafficlight.setPhase(tls_id, 0)
                print(f"MANUAL CONTROL: Set {tls_id} to GREEN (Phase 0) - RL agent paused")
                return True
            elif phase_name == 'Yellow':
                traci.trafficlight.setPhase(tls_id, 1)
                print(f"MANUAL CONTROL: Set {tls_id} to YELLOW (Phase 1) - RL agent paused")
                return True
            elif phase_name == 'Red':
                traci.trafficlight.setPhase(tls_id, 2)
                print(f"MANUAL CONTROL: Set {tls_id} to RED (Phase 2) - RL agent paused")
                return True
        except Exception as e:
            print(f"ERROR setting traffic light {tls_id}: {str(e)}")
            return False
        return False

    def clear_emergency_override():
        """Clear emergency override and return control to RL agent"""
        try:
            with data_lock:
                shared_simulation_data['emergency_override'] = False
            print("Emergency override cleared - RL agent resumed")
            return True
        except Exception as e:
            print(f"ERROR clearing emergency: {str(e)}")
            return False

    # -------------------------
    # SUMO Simulation Thread
    # -------------------------

    def run_sumo_simulation(total_steps=10000):
        global last_switch_step, Q_table, shared_simulation_data
        
        with data_lock:
            shared_simulation_data['running'] = True
        
        try:
            try:
                traci.close()
            except:
                pass
            
            sumo_config = [
                'sumo-gui',
                '-c', 'C:/Users/Mohammad/Desktop/SNP/RL.sumocfg',
                '--step-length', '0.10',
                '--delay', '10',
                '--lateral-resolution', '0',
                '--start', 'true',
                '--quit-on-end', 'false'
            ]
            
            traci.start(sumo_config)
            
            try:
                traci.gui.setSchema("View #0", "real world")
            except:
                pass
            
            cumulative_reward = 0.0
            cumulative_waiting_time_total = 0.0
            
            with data_lock:
                shared_simulation_data['queue_data'] = []
                shared_simulation_data['waiting_time_data'] = []
                shared_simulation_data['reward_data'] = []
                shared_simulation_data['phase_data'] = []
            
            print(f"Starting simulation for {total_steps} steps...")
            
            for step in range(total_steps):
                with data_lock:
                    if not shared_simulation_data['running']:
                        print("Simulation stopped by user")
                        break
                
                if traci.simulation.getMinExpectedNumber() <= 0 and step > 100:
                    print(f"No more vehicles in simulation at step {step}")
                    break
                
                with data_lock:
                    shared_simulation_data['step'] = step
                
                try:
                    state = get_state()
                    
                    with data_lock:
                        emergency_active = shared_simulation_data.get('emergency_override', False)
                    
                    if not emergency_active:
                        action = get_action_from_policy(state)
                        apply_action(action, step)
                    else:
                        action = 0
                    
                    traci.simulationStep()
                    
                    new_state = get_state()
                    
                    if len(state) > 0 and len(new_state) > 0:
                        if state[-1] != new_state[-1]:
                            cumulative_waiting_time_total += sum(new_state[-7:-1])
                    
                    reward = get_reward(new_state)
                    cumulative_reward += reward
                    cumulative_waiting_time = sum(new_state[-7:-1])
                    
                    if not emergency_active:
                        update_Q_table(state, action, reward, new_state)
                    
                    with data_lock:
                        shared_simulation_data['queue_data'].append({
                            'step': step,
                            'total_queue': sum(new_state[0:6]),
                            'q_EB_0': new_state[0],
                            'q_EB_1': new_state[1],
                            'q_EB_2': new_state[2],
                            'q_SB_0': new_state[3],
                            'q_SB_1': new_state[4],
                            'q_SB_2': new_state[5]
                        })
                        
                        shared_simulation_data['waiting_time_data'].append({
                            'step': step,
                            'cumulative_waiting': cumulative_waiting_time,
                            'total_waiting': cumulative_waiting_time_total
                        })
                        
                        shared_simulation_data['reward_data'].append({
                            'step': step,
                            'reward': cumulative_reward
                        })
                        
                        shared_simulation_data['phase_data'].append({
                            'step': step,
                            'phase': new_state[-1]
                        })
                        
                        shared_simulation_data['q_table_size'] = len(Q_table)
                        shared_simulation_data['cumulative_reward'] = cumulative_reward
                        shared_simulation_data['cumulative_waiting_time'] = cumulative_waiting_time_total
                        shared_simulation_data['last_update'] = datetime.datetime.now()
                    
                    if step % 100 == 0:
                        with data_lock:
                            emergency_active = shared_simulation_data.get('emergency_override', False)
                        
                        if emergency_active:
                            print(f"Step {step}: Queue={sum(new_state[0:6])}, Reward={cumulative_reward:.2f} [EMERGENCY MODE - RL paused]")
                        else:
                            print(f"Step {step}: Queue={sum(new_state[0:6])}, Reward={cumulative_reward:.2f}, Q-table size={len(Q_table)}")
                            
                            if len(Q_table) > 0:
                                print("\nRecent Q-Table Entries:")
                                for state, q_vals in list(Q_table.items())[-5:]:
                                    q_str = f"[{q_vals[0]:.4f}, {q_vals[1]:.4f}]"
                                    print(f"State: {state} -> Q-values: {q_str}")
                                print()
                        
                except Exception as e:
                    print(f"Error at step {step}: {str(e)}")
                    continue
            
            print(f"Simulation completed at step {step}")
            with data_lock:
                print(f"Total data points collected: {len(shared_simulation_data['queue_data'])}")
                print(f"Q-Table size: {len(Q_table)}")
                print(f"Final cumulative reward: {shared_simulation_data['cumulative_reward']:.2f}")
                print(f"Final waiting time: {shared_simulation_data['cumulative_waiting_time']:.2f}s")
                print("=" * 70)
                
                if len(Q_table) > 0:
                    print("\n" + "=" * 70)
                    print("COMPLETE Q-TABLE - ALL LEARNED STATES")
                    print("=" * 70)
                    for state, q_vals in Q_table.items():
                        q_str = f"[{q_vals[0]:.4f}, {q_vals[1]:.4f}]"
                        print(f"State: {state} -> Q-values: {q_str}")
                    print("=" * 70)
                    print(f"Total states learned: {len(Q_table)}")
                    print("=" * 70 + "\n")
            
            traci.close()
            with data_lock:
                shared_simulation_data['running'] = False
            
        except Exception as e:
            error_msg = f"Simulation error: {str(e)}"
            print(error_msg)
            with data_lock:
                shared_simulation_data['running'] = False
                shared_simulation_data['error'] = error_msg
            try:
                traci.close()
            except:
                pass

    # -------------------------
    # Streamlit Dashboard
    # -------------------------

    st.set_page_config(page_title="Traffic Light Dashboard", layout="wide")

    def get_simulation_data():
        with data_lock:
            return {
                'running': shared_simulation_data['running'],
                'step': shared_simulation_data['step'],
                'queue_data': shared_simulation_data['queue_data'].copy(),
                'waiting_time_data': shared_simulation_data['waiting_time_data'].copy(),
                'reward_data': shared_simulation_data['reward_data'].copy(),
                'phase_data': shared_simulation_data['phase_data'].copy(),
                'q_table_size': shared_simulation_data['q_table_size'],
                'cumulative_reward': shared_simulation_data['cumulative_reward'],
                'cumulative_waiting_time': shared_simulation_data['cumulative_waiting_time'],
                'last_update': shared_simulation_data['last_update'],
                'emergency_override': shared_simulation_data.get('emergency_override', False)
            }

    simulation_data = get_simulation_data()

    # Add logout button
    with st.sidebar:
        st.write(f"Logged in as: **{st.session_state.user['full_name']}**")
        
        if st.button("Logout", type="secondary"):
            st.session_state.authenticated = False
            st.session_state.user = None
            st.rerun()
        
        st.divider()

    st.title("🚦 Traffic Light Management Dashboard")

    # Sidebar for simulation control
    with st.sidebar:
        st.header("Simulation Control")
        
        if 'error' in simulation_data and simulation_data.get('error'):
            st.error(f"Error: {simulation_data['error']}")
        
        if not st.session_state.simulation_started:
            total_steps = st.number_input("Total Simulation Steps", min_value=1000, max_value=50000, value=10000, step=1000)
            
            if st.button("Start Simulation", type="primary", width='stretch'):
                with data_lock:
                    shared_simulation_data['queue_data'] = []
                    shared_simulation_data['waiting_time_data'] = []
                    shared_simulation_data['reward_data'] = []
                    shared_simulation_data['phase_data'] = []
                    shared_simulation_data['step'] = 0
                    shared_simulation_data['q_table_size'] = 0
                    shared_simulation_data['cumulative_reward'] = 0
                    shared_simulation_data['cumulative_waiting_time'] = 0
                    shared_simulation_data['running'] = True
                    
                    if 'error' in shared_simulation_data:
                        del shared_simulation_data['error']
                
                st.session_state.simulation_started = True
                st.session_state.sumo_thread = threading.Thread(
                    target=run_sumo_simulation, 
                    args=(total_steps,),
                    daemon=True
                )
                st.session_state.sumo_thread.start()
                st.success("Simulation started!")
                time.sleep(1)
                st.rerun()
        else:
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("⏹️ Stop", type="secondary", width='stretch'):
                    with data_lock:
                        shared_simulation_data['running'] = False
                    st.session_state.simulation_started = False
                    st.warning("Stopping...")
                    time.sleep(1)
                    st.rerun()
            
            with col2:
                if st.button("🔄 Restart", type="primary", width='stretch'):
                    with data_lock:
                        shared_simulation_data['running'] = False
                    st.session_state.simulation_started = False
                    time.sleep(0.5)
                    st.rerun()
            
            st.divider()
            
            thread_alive = st.session_state.sumo_thread is not None and st.session_state.sumo_thread.is_alive()
            
            with data_lock:
                live_running = shared_simulation_data['running']
                live_step = shared_simulation_data['step']
                live_data_points = len(shared_simulation_data['queue_data'])
            
            if live_running and thread_alive:
                st.success("🟢 Simulation Active")
            elif thread_alive:
                st.info("🔵 Simulation Processing...")
            else:
                st.warning("🟡 Simulation Ended")
            
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                st.metric("Step", live_step)
            with col_m2:
                st.metric("Data Points", live_data_points)
            
            st.metric("Q-Table Size", simulation_data['q_table_size'])
        
        st.divider()
        
        st.header("RL Parameters")
        st.caption("Adjust parameters for simulation")
        st.session_state.rl_params['ALPHA'] = st.slider("Learning Rate (α)", 0.01, 1.0, st.session_state.rl_params['ALPHA'], 0.01)
        st.session_state.rl_params['GAMMA'] = st.slider("Discount Factor (γ)", 0.1, 1.0, st.session_state.rl_params['GAMMA'], 0.01)
        st.session_state.rl_params['EPSILON'] = st.slider("Exploration Rate (ε)", 0.0, 1.0, st.session_state.rl_params['EPSILON'], 0.01)
        st.session_state.rl_params['MIN_GREEN_STEPS'] = st.slider("Min Green Steps", 50, 200, st.session_state.rl_params['MIN_GREEN_STEPS'], 10)

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "🎛️ Manual Control", "🚨 Emergency", "⚙️ Settings"])

    with tab1:
        st.subheader("Live Traffic Data")
        
        thread_alive = st.session_state.sumo_thread is not None and st.session_state.sumo_thread.is_alive()
        
        if simulation_data['running'] and thread_alive:
            st.success(f"🟢 Simulation Running - Step {simulation_data['step']} - Collected {len(simulation_data['queue_data'])} data points")
        elif thread_alive:
            st.info(f"🔵 Simulation Processing - Step {simulation_data['step']} - Collected {len(simulation_data['queue_data'])} data points")
        elif len(simulation_data['queue_data']) > 0:
            st.info(f"⏹️ Simulation Completed - Total Steps: {simulation_data['step']} - Data Points: {len(simulation_data['queue_data'])}")
        
        if len(simulation_data['queue_data']) > 0:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Cumulative Reward", f"{simulation_data['cumulative_reward']:.0f}")
            
            with col2:
                waiting_time_str = str(datetime.timedelta(seconds=int(simulation_data['cumulative_waiting_time'])))
                st.metric("Total Waiting Time", waiting_time_str)
            
            with col3:
                current_phase = simulation_data['phase_data'][-1]['phase'] if simulation_data['phase_data'] else 0
                st.metric("Current Phase", current_phase)
            
            with col4:
                total_queue = simulation_data['queue_data'][-1]['total_queue'] if simulation_data['queue_data'] else 0
                st.metric("Current Total Queue", int(total_queue))
            
            st.divider()
            
            st.write("**Recent Queue Data (Last 20 Steps)**")
            if simulation_data['queue_data']:
                df_queue = pd.DataFrame(simulation_data['queue_data'][-20:])
                
                column_mapping = {
                    'step': 'Step',
                    'total_queue': 'Total Queue',
                    'q_EB_0': 'Eastbound Lane 1',
                    'q_EB_1': 'Eastbound Lane 2',
                    'q_EB_2': 'Eastbound Lane 3',
                    'q_SB_0': 'Southbound Lane 1',
                    'q_SB_1': 'Southbound Lane 2',
                    'q_SB_2': 'Southbound Lane 3'
                }
                
                df_queue = df_queue.rename(columns=column_mapping)
                st.dataframe(df_queue, width='stretch', height=300)
            
            st.divider()
            
            if len(simulation_data['queue_data']) > 1:
                df_queue_plot = pd.DataFrame(simulation_data['queue_data'])
                
                fig1 = px.line(df_queue_plot, x='step', y='total_queue', 
                              title='Total Queue Length Over Time',
                              labels={'step': 'Simulation Step', 'total_queue': 'Queue Length'})
                fig1.update_traces(line_color='#FF4B4B', line_width=2)
                fig1.update_layout(height=400)
                st.plotly_chart(fig1, width='stretch')
                
                fig_lanes = go.Figure()
                colors = ['#FF4B4B', '#FFA500', '#FFD700', '#00CED1', '#1E90FF', '#9370DB']
                
                lane_names = {
                    'q_EB_0': 'Eastbound Lane 1',
                    'q_EB_1': 'Eastbound Lane 2',
                    'q_EB_2': 'Eastbound Lane 3',
                    'q_SB_0': 'Southbound Lane 1',
                    'q_SB_1': 'Southbound Lane 2',
                    'q_SB_2': 'Southbound Lane 3'
                }
                
                lanes = ['q_EB_0', 'q_EB_1', 'q_EB_2', 'q_SB_0', 'q_SB_1', 'q_SB_2']
                
                for lane, color in zip(lanes, colors):
                    fig_lanes.add_trace(go.Scatter(
                        x=df_queue_plot['step'], 
                        y=df_queue_plot[lane], 
                        mode='lines', 
                        name=lane_names[lane],
                        line=dict(color=color, width=2)
                    ))
                
                fig_lanes.update_layout(
                    title='Individual Lane Queue Lengths', 
                    xaxis_title='Simulation Step', 
                    yaxis_title='Queue Length (vehicles)',
                    height=400,
                    hovermode='x unified',
                    legend=dict(
                        orientation="v",
                        yanchor="top",
                        y=1,
                        xanchor="left",
                        x=1.01
                    )
                )
                st.plotly_chart(fig_lanes, width='stretch')
            
            if len(simulation_data['reward_data']) > 1:
                df_reward = pd.DataFrame(simulation_data['reward_data'])
                fig2 = px.line(df_reward, x='step', y='reward', 
                              title='Cumulative Reward Over Time',
                              labels={'step': 'Simulation Step', 'reward': 'Cumulative Reward'})
                fig2.update_traces(line_color='#00CED1', line_width=2)
                fig2.update_layout(height=400)
                st.plotly_chart(fig2, width='stretch')
            
            if len(simulation_data['waiting_time_data']) > 1:
                df_waiting = pd.DataFrame(simulation_data['waiting_time_data'])
                
                col_wait1, col_wait2 = st.columns(2)
                
                with col_wait1:
                    fig3 = px.line(df_waiting, x='step', y='cumulative_waiting', 
                                  title='Instantaneous Waiting Time',
                                  labels={'step': 'Simulation Step', 'cumulative_waiting': 'Waiting Time (s)'})
                    fig3.update_traces(line_color='#FFA500', line_width=2)
                    fig3.update_layout(height=350)
                    st.plotly_chart(fig3, width='stretch')
                
                with col_wait2:
                    fig4 = px.line(df_waiting, x='step', y='total_waiting', 
                                  title='Total Cumulative Waiting Time',
                                  labels={'step': 'Simulation Step', 'total_waiting': 'Total Waiting Time (s)'})
                    fig4.update_traces(line_color='#9370DB', line_width=2)
                    fig4.update_layout(height=350)
                    st.plotly_chart(fig4, width='stretch')
        else:
            st.info("Start the simulation from the sidebar to see live data")

    with tab2:
        st.subheader("Manual Control")
        
        show_messages()
        
        st.info("Control Traffic Lights Manually")
        
        col1, col2 = st.columns(2)
        
        with col1:
            light_state = st.radio("Set Light State", ['Green', 'Yellow', 'Red'])
        
        with col2:
            if st.button("Apply Light State", type="primary"):
                if simulation_data['running']:
                    success = set_traffic_light_phase("Node2", light_state)
                    if success:
                        add_message('success', f"Node2 set to {light_state} mode - RL agent paused", duration=3)
                        st.rerun()
                    else:
                        add_message('error', f"Failed to set light state for Node2.", duration=3)
                        st.rerun()
                else:
                    add_message('warning', "Please start the simulation first!", duration=3)
                    st.rerun()
        
        if st.button("Resume RL Agent", type="secondary"):
            if simulation_data['running']:
                success = clear_emergency_override()
                if success:
                    add_message('success', "RL agent resumed - automatic control active", duration=3)
                    st.rerun()
            else:
                add_message('info', "No simulation running", duration=3)
                st.rerun()
        
        duration = st.slider("Set Duration (seconds)", 5, 120, 30)
        st.info(f"Signal duration set to {duration} seconds")
        
        st.divider()
        
        if simulation_data.get('emergency_override', False):
            st.warning("⚠ MANUAL MODE - RL agent paused")
        else:
            st.success("Automatic mode - RL agent active")
        
        st.divider()
        
        st.write("**Current Traffic Light State:**")
        
        if simulation_data['running'] or len(simulation_data['phase_data']) > 0:
            try:
                if simulation_data['phase_data']:
                    current_phase = simulation_data['phase_data'][-1]['phase']
                    st.metric(f"Node2 - Current Phase Index", current_phase)
                    
                    phase_meanings = {
                        0: "🟢 Green - Main direction",
                        1: "🟡 Yellow - Transition",
                        2: "🟢 Green - Cross direction",
                        3: "🟡 Yellow - Transition"
                    }
                    
                    phase_description = phase_meanings.get(current_phase, 'Unknown')
                    st.info(f"Phase {current_phase}: {phase_description}")
            except:
                st.info("Waiting for simulation data...")
        else:
            st.info("Start simulation to see current state")

    with tab3:
        st.subheader("Emergency Control Panel")
        
        show_messages()
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("Activate Emergency Override", type="primary", width='stretch'):
                if simulation_data['running']:
                    success, direction = activate_emergency_smart("Node2")
                    if success:
                        add_message('error', f"🚨 Emergency activated - {direction} direction GREEN!", duration=3)
                else:
                    add_message('warning', "Please start the simulation first!", duration=3)
        
        with col2:
            if st.button("Clear Emergency", type="secondary", width='stretch'):
                if simulation_data['running']:
                    success = clear_emergency_override()
                    if success:
                        add_message('success', "Emergency cleared at Node2", duration=3)
                else:
                    add_message('info', "No simulation running", duration=3)
        
        st.divider()
        
        if simulation_data.get('emergency_override', False):
            st.error("🚨 EMERGENCY MODE ACTIVE - RL agent disabled")
        else:
            st.success("Normal operation - RL agent controlling traffic")

    with tab4:
        st.subheader("Reinforcement Learning Parameters")
        
        st.info("Adjust RL parameters from the sidebar. Changes apply to new learning steps.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Learning Rate (α)", f"{st.session_state.rl_params['ALPHA']:.2f}")
            st.metric("Discount Factor (γ)", f"{st.session_state.rl_params['GAMMA']:.2f}")
        
        with col2:
            st.metric("Exploration Rate (ε)", f"{st.session_state.rl_params['EPSILON']:.2f}")
            st.metric("Min Green Steps", st.session_state.rl_params['MIN_GREEN_STEPS'])
        
        st.divider()
        
        st.subheader("Q-Table Statistics")
        
        q_table_size = simulation_data.get('q_table_size', 0)
        
        if q_table_size > 0:
            st.metric("Q-Table Size (States Learned)", q_table_size)
            
            q_table_snapshot = simulation_data.get('q_table_snapshot', [])
            
            if q_table_snapshot and len(q_table_snapshot) > 0:
                st.write("**Q-Learning Table - Learned State-Action Values:**")
                st.caption("Shows the last 20 states the agent has learned with their Q-values")
                
                q_table_data = []
                
                for state, q_values in q_table_snapshot:
                    state_str = f"({state[0]}, {state[1]}, {state[2]}, {state[3]}, {state[4]}, {state[5]}, {state[6]:.1f}, {state[7]:.1f}, {state[8]:.1f}, {state[9]:.1f}, {state[10]:.1f}, {state[11]:.1f}, {state[12]})"
                    
                    q_table_data.append({
                        'State (q_EB_0, q_EB_1, q_EB_2, q_SB_0, q_SB_1, q_SB_2, wt_EB_0, wt_EB_1, wt_EB_2, wt_SB_0, wt_SB_1, wt_SB_2, phase)': state_str,
                        'Q-Values': f"[{q_values[0]:8.4f}, {q_values[1]:8.4f}]",
                        'Best Action': 'Switch' if q_values[1] > q_values[0] else '⏸️ Keep'
                    })
                
                if q_table_data:
                    df_qtable = pd.DataFrame(q_table_data)
                    st.dataframe(df_qtable, width='stretch', height=500)
                    
                    st.caption("💡 **Reading the Q-Table:**")
                    st.caption("- **State**: (queue_EB_lanes, queue_SB_lanes, waiting_EB_lanes, waiting_SB_lanes, phase)")
                    st.caption("- **Q-Values**: [Q(Keep) Q(Switch)] - Higher value is better action")
                    st.caption("- **Best Action**: Recommended action based on learned Q-values")
        else:
            st.info("Q-Table will populate once simulation starts")
        
        st.divider()
        
        st.success(f"RL Settings Active: α = {st.session_state.rl_params['ALPHA']}, γ = {st.session_state.rl_params['GAMMA']}, ε = {st.session_state.rl_params['EPSILON']}")

    # Auto-refresh logic
    thread_alive = st.session_state.sumo_thread is not None and st.session_state.sumo_thread.is_alive()

    with data_lock:
        is_running = shared_simulation_data['running']

    if is_running and thread_alive:
        time.sleep(1)
        st.rerun()
    
    # Stop execution here since we're in dashboard
    st.stop()

# Login Page (only shown if not authenticated)
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.markdown('<div class="login-container">', unsafe_allow_html=True)
    
    # Header
    st.markdown('<h3 style="text-align: center; color: #667eea;">Administrator Login</h3>', unsafe_allow_html=True)
    st.markdown('<br>', unsafe_allow_html=True)
    
    # Login form
    with st.form("login_form"):
        email = st.text_input(
            "Email Address",
            placeholder="name@moi.gov.sa",
            help="Enter your Ministry of Interior email"
        )
        
        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password",
            help="Your secure password"
        )
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        submit = st.form_submit_button("Login", type="primary")
        
        if submit:
            if email and password:
                # Validate email domain
                if not validate_email_domain(email):
                    st.error("Email must be from @moi.gov.sa domain")
                else:
                    with st.spinner("Authenticating..."):
                        user, error = authenticate_user(email, password)
                        
                        if user:
                            st.session_state.authenticated = True
                            st.session_state.user = user
                            st.success(f"Welcome, {user['full_name']}!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"{error}")
            else:
                st.warning("Please enter both email and password")
    
    st.markdown('</div>', unsafe_allow_html=True)
