import numpy as np
import pickle

class TicTacToeAgent:
    def __init__(self):
        self.q_table = {}
        self.epsilon = 0.1  # Exploration rate
        self.alpha = 0.5    # Learning rate
        self.gamma = 0.9    # Discount factor

    def get_state_key(self, state):
        return ''.join(map(str, state.flatten()))

    def select_action(self, state):
        state_key = self.get_state_key(state)
        if state_key not in self.q_table:
            self.q_table[state_key] = [0] * 9  # Initialize Q-values for each action

        available_actions = np.where(state.flatten() == 0)[0]
        if len(available_actions) == 0:
            return None  # No moves left

        if np.random.rand() < self.epsilon:
            # Explore: choose a random available action
            return np.random.choice(available_actions)
        else:
            # Exploit: choose the best available action
            q_values = np.array(self.q_table[state_key])
            # Mask invalid actions
            masked_q = np.full_like(q_values, -np.inf)
            masked_q[available_actions] = q_values[available_actions]
            return int(np.argmax(masked_q))

    def update_strategy(self, state, action, reward, next_state):
        state_key = self.get_state_key(state)
        next_state_key = self.get_state_key(next_state)
        if next_state_key not in self.q_table:
            self.q_table[next_state_key] = [0] * 9
        best_next_action = np.argmax(self.q_table[next_state_key])
        td_target = reward + self.gamma * self.q_table[next_state_key][best_next_action]
        td_delta = td_target - self.q_table[state_key][action]
        self.q_table[state_key][action] += self.alpha * td_delta

    def save(self, filename="q_table.pkl"):
        with open(filename, "wb") as f:
            pickle.dump(self.q_table, f)

    def load(self, filename="q_table.pkl"):
        with open(filename, "rb") as f:
            self.q_table = pickle.load(f)