import random

class MyAgent:
    def choose_action(self, board, legal_actions):
        return random.choice(list(legal_actions))
