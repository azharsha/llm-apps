import numpy as np
from src.agent import TicTacToeAgent
from src.environment import TicTacToeEnvironment

def print_board(board):
    symbols = [' ', 'X', 'O']
    for i in range(3):
        row = [symbols[board[j]] for j in range(i*3, (i+1)*3)]
        print('|'.join(row))
        if i < 2:
            print('-+-+-')

def main():
    env = TicTacToeEnvironment()
    agent = TicTacToeAgent()
    agent.load()           # Load the trained Q-table
    agent.epsilon = 0      # Always exploit learned policy
    state = env.reset()
    done = False

    print("Welcome to Tic Tac Toe! You are X (1), AI is O (2).")
    print_board(state)

    while not done:
        # Human move
        available = [i for i in range(9) if state[i] == 0]
        move = -1
        while move not in available:
            try:
                move = int(input(f"Your move (0-8): "))
            except ValueError:
                continue
        state, reward, done = env.step(move)
        print_board(state)
        if done:
            last_player = 1  # Human
            break

        # AI move
        ai_move = agent.select_action(state)
        print(f"AI chooses: {ai_move}")
        state, reward, done = env.step(ai_move)
        print_board(state)
        if done:
            last_player = 2  # AI
            break

    # Game over message
    if reward == 1:
        if last_player == 1:
            print("You win!")
        else:
            print("AI wins!")
    else:
        print("It's a draw!")

if __name__ == "__main__":
    main()