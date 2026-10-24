from agent import MyAgent

def toy_env(steps=5):
    board = [[0]*5 for _ in range(5)]
    legal = ['up','down','left','right']
    return board, legal

def test_random_runs():
    a = MyAgent()
    board, legal = toy_env()
    for _ in range(5):
        act = a.choose_action(board, legal)
        assert act in legal
    print('BASELINE_OK')
