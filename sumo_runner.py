"""SUMO + TraCI simulation functions."""
from __future__ import annotations

import datetime as dt
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from config import SUMO_CONFIG_PATH
from rl_agent import QLearningAgent


def prepare_sumo_tools() -> None:
    """Add SUMO tools folder to Python path."""
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        raise EnvironmentError("Please set the SUMO_HOME environment variable before running the simulation.")
    tools = Path(sumo_home) / "tools"
    if str(tools) not in sys.path:
        sys.path.append(str(tools))


def get_queue_length(traci, detector_id: str) -> int:
    try:
        return traci.lanearea.getLastStepVehicleNumber(detector_id)
    except Exception:
        return 0


def get_waiting_time(traci, detector_id: str) -> float:
    try:
        return traci.lane.getWaitingTime(detector_id)
    except Exception:
        return 0


def get_current_phase(traci, tls_id: str = "Node2") -> int:
    try:
        return traci.trafficlight.getPhase(tls_id)
    except Exception:
        return 0


def get_state(traci, tls_id: str = "Node2") -> tuple:
    detectors = [
        "Node1_2_EB_0", "Node1_2_EB_1", "Node1_2_EB_2",
        "Node2_7_SB_0", "Node2_7_SB_1", "Node2_7_SB_2",
    ]
    queues = [get_queue_length(traci, detector) for detector in detectors]
    waiting_times = [get_waiting_time(traci, detector) for detector in detectors]
    return tuple(queues + waiting_times + [get_current_phase(traci, tls_id)])


def apply_action(traci, agent: QLearningAgent, action: int, current_step: int, tls_id: str = "Node2") -> None:
    if action != 1:
        return
    if current_step - agent.last_switch_step >= agent.min_green_steps:
        try:
            program = traci.trafficlight.getAllProgramLogics(tls_id)[0]
            next_phase = (get_current_phase(traci, tls_id) + 1) % len(program.phases)
            traci.trafficlight.setPhase(tls_id, next_phase)
            agent.last_switch_step = current_step
        except Exception:
            pass


def detect_emergency_vehicle_direction(traci) -> Optional[str]:
    for vehicle_id in traci.vehicle.getIDList():
        try:
            if traci.vehicle.getVehicleClass(vehicle_id) != "emergency":
                continue
            edge_id = traci.vehicle.getRoadID(vehicle_id)
            if "Node1_2" in edge_id or "Node2_3" in edge_id:
                return "EW"
            if "Node2_7" in edge_id or "Node2_5" in edge_id:
                return "NS"
        except Exception:
            continue
    return None


def start_sumo(traci):
    config_path = str(SUMO_CONFIG_PATH)
    traci.start([
        "sumo-gui",
        "-c", config_path,
        "--step-length", "0.10",
        "--delay", "10",
        "--lateral-resolution", "0",
        "--start", "true",
        "--quit-on-end", "false",
    ])
    try:
        traci.gui.setSchema("View #0", "real world")
    except Exception:
        pass


def run_simulation(shared_data: dict, data_lock: threading.Lock, agent: QLearningAgent, total_steps: int = 10000) -> None:
    prepare_sumo_tools()
    import traci

    with data_lock:
        shared_data["running"] = True

    try:
        try:
            traci.close()
        except Exception:
            pass

        start_sumo(traci)
        cumulative_reward = 0.0
        total_waiting_time = 0.0

        with data_lock:
            shared_data.update({
                "queue_data": [],
                "waiting_time_data": [],
                "reward_data": [],
                "phase_data": [],
                "q_table_snapshot": [],
                "error": None,
            })

        for step in range(total_steps):
            with data_lock:
                if not shared_data.get("running", False):
                    break
                emergency_override = shared_data.get("emergency_override", False)
                shared_data["step"] = step

            if traci.simulation.getMinExpectedNumber() <= 0 and step > 100:
                break

            old_state = get_state(traci)
            action = 0 if emergency_override else agent.choose_action(old_state)
            if not emergency_override:
                apply_action(traci, agent, action, step)

            traci.simulationStep()
            new_state = get_state(traci)
            reward = agent.reward(new_state)
            cumulative_reward += reward
            instant_waiting = sum(new_state[6:12])
            total_waiting_time += instant_waiting

            if not emergency_override:
                agent.update(old_state, action, reward, new_state)

            with data_lock:
                shared_data["queue_data"].append({
                    "step": step,
                    "total_queue": sum(new_state[:6]),
                    "q_EB_0": new_state[0], "q_EB_1": new_state[1], "q_EB_2": new_state[2],
                    "q_SB_0": new_state[3], "q_SB_1": new_state[4], "q_SB_2": new_state[5],
                })
                shared_data["waiting_time_data"].append({
                    "step": step,
                    "instant_waiting": instant_waiting,
                    "total_waiting": total_waiting_time,
                })
                shared_data["reward_data"].append({"step": step, "reward": cumulative_reward})
                shared_data["phase_data"].append({"step": step, "phase": new_state[-1]})
                shared_data["q_table_size"] = len(agent.q_table)
                shared_data["q_table_snapshot"] = agent.snapshot()
                shared_data["cumulative_reward"] = cumulative_reward
                shared_data["cumulative_waiting_time"] = total_waiting_time
                shared_data["last_update"] = dt.datetime.now()

        traci.close()
    except Exception as exc:
        with data_lock:
            shared_data["error"] = str(exc)
    finally:
        with data_lock:
            shared_data["running"] = False
