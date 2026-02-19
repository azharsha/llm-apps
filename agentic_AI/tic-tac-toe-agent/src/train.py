import gymnasium as gym
import numpy as np
from src.agent import TicTacToeAgent
from src.environment import TicTacToeEnvironment

def train_agent(episodes=500000):
    env = TicTacToeEnvironment()
    agent = TicTacToeAgent()
    for episode in range(episodes):
        state = env.reset()
        done = False
        # Alternate who starts
        env.current_player = 1 if episode % 2 == 0 else 2
        agent_last_state = None
        agent_last_action = None

        while not done:
            current_player = env.current_player
            if current_player == 1:
                action = agent.select_action(state)
                agent_last_state = state
                agent_last_action = action
            else:
                available = [i for i in range(9) if state[i] == 0]
                action = np.random.choice(available)
            state, reward, done = env.step(action)

            if current_player == 1:
                agent.update_strategy(agent_last_state, agent_last_action, reward, state)

        # After the game ends, if the agent lost, penalize its last move
        if reward == 1 and current_player != 1 and agent_last_state is not None:
            agent.update_strategy(agent_last_state, agent_last_action, -1, state)

        if episode % 10000 == 0:
            print(f"Episode {episode}")

    return agent

if __name__ == "__main__":
    agent = train_agent(episodes=500000)
    agent.save()

def step(self, action):
    if self.board[action] != 0:
        return self.board.copy(), -10, True  # Invalid move

    self.board[action] = self.current_player
    reward = 0
    done = False

    if self.is_winner(self.current_player):
        reward = 1
        done = True
    elif self.is_draw():
        reward = 0
        done = True
    else:
        self.current_player = 2 if self.current_player == 1 else 1

    return self.board.copy(), reward, done