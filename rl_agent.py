"""Q-learning logic for traffic light decisions."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, Tuple

import numpy as np

State = Tuple[int, ...]


@dataclass
class QLearningAgent:
    alpha: float = 0.1
    gamma: float = 0.9
    epsilon: float = 0.1
    min_green_steps: int = 100
    actions: tuple = (0, 1)  # 0 = keep current phase, 1 = switch phase
    q_table: Dict[State, np.ndarray] = field(default_factory=dict)
    last_switch_step: int = -100

    def ensure_state(self, state: State) -> None:
        if state not in self.q_table:
            self.q_table[state] = np.zeros(len(self.actions))

    def reward(self, state: State) -> float:
        # Lower total queue is better, so reward is negative queue length.
        return -float(sum(state[:6]))

    def choose_action(self, state: State) -> int:
        self.ensure_state(state)
        if random.random() < self.epsilon:
            return random.choice(self.actions)
        return int(np.argmax(self.q_table[state]))

    def update(self, old_state: State, action: int, reward: float, new_state: State) -> None:
        self.ensure_state(old_state)
        self.ensure_state(new_state)
        old_q = self.q_table[old_state][action]
        best_future_q = np.max(self.q_table[new_state])
        self.q_table[old_state][action] = old_q + self.alpha * (reward + self.gamma * best_future_q - old_q)

    def snapshot(self, limit: int = 20):
        return list(self.q_table.items())[-limit:]
