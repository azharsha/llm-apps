import numpy as np

class TicTacToeEnvironment:
    def __init__(self):
        self.reset()

    def reset(self):
        self.board = np.zeros(9, dtype=int)
        self.current_player = 1
        return self.board.copy()

    def is_winner(self, player):
        win_conditions = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],  # horizontal
            [0, 3, 6], [1, 4, 7], [2, 5, 8],  # vertical
            [0, 4, 8], [2, 4, 6]              # diagonal
        ]
        return any(all(self.board[i] == player for i in condition) for condition in win_conditions)

    def is_draw(self):
        return np.all(self.board != 0)

    def take_action(self, action):
        if self.board[action] == ' ':
            self.board[action] = self.current_player
            if self.is_winner(self.current_player):
                return 1  # Win
            elif self.is_draw():
                return 0  # Draw
            else:
                self.current_player = 'O' if self.current_player == 'X' else 'X'
                return None  # Continue
        else:
            raise ValueError("Invalid action")

    def get_available_actions(self):
        return [i for i in range(9) if self.board[i] == ' ']

    def get_current_state(self):
        return np.array(self.board.copy())
    
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