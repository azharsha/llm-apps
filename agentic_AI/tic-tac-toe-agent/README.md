# Tic Tac Toe Agent

This project implements a Q-learning agent that plays Tic Tac Toe. The agent learns to play by playing against a random opponent and updates its strategy using reinforcement learning.

## Project Structure

```
tic-tac-toe-agent/
├── src/
│   ├── agent.py            # Q-learning agent implementation
│   ├── environment.py      # Tic Tac Toe environment logic
│   ├── train.py            # Training loop for the agent
│   └── play.py             # Play against the trained agent in the terminal
├── requirements.txt
└── README.md
```

## Requirements

- Python 3.8+
- numpy

Install dependencies:
```sh
pip install -r requirements.txt
```

## Training the Agent

To train the agent (recommended: 500,000+ episodes):

```sh
python -m src.train
```

This will create a `q_table.pkl` file with the trained Q-table.

## Playing Against the Agent

After training, play against the agent in the terminal:

```sh
python -m src.play
```

- You are X (1), the AI is O (2).
- Enter your move as a number from 0 to 8 (top-left to bottom-right).

## How It Works

- The agent uses Q-learning to update its strategy.
- During training, the agent alternates starting positions and plays against a random opponent.
- The agent is penalized for invalid moves and for losing, and rewarded for winning.

## Example Training Loop

```python
def train_agent(episodes=500000):
    env = TicTacToeEnvironment()
    agent = TicTacToeAgent()
    for episode in range(episodes):
        state = env.reset()
        done = False
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

        # Penalize agent for losing
        if reward == 1 and current_player != 1 and agent_last_state is not None:
            agent.update_strategy(agent_last_state, agent_last_action, -1, state)

        if episode % 10000 == 0:
            print(f"Episode {episode}")

    return agent
```

## Contributions

Contributions are welcome! Please open an issue or submit a pull request.
