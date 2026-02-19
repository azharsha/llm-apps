def render_board(board):
    for row in board:
        print(" | ".join(row))
        print("-" * 9)

def log_results(results, filename="results.log"):
    with open(filename, "a") as f:
        for result in results:
            f.write(f"{result}\n")

def save_model(agent, filename):
    import pickle
    with open(filename, "wb") as f:
        pickle.dump(agent, f)

def load_model(filename):
    import pickle
    with open(filename, "rb") as f:
        return pickle.load(f)