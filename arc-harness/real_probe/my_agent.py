import random

from arcengine import FrameData, GameAction, GameState
from agents.agent import Agent


class MyAgent(Agent):
    MAX_ACTIONS = 30

    def is_done(self, frames, latest_frame):
        return latest_frame.state is GameState.WIN

    def choose_action(self, frames, latest_frame):
        if latest_frame.state in (GameState.NOT_PLAYED, GameState.GAME_OVER):
            return GameAction.RESET
        cands = [a for a in GameAction if a is not GameAction.RESET]
        a = random.choice(cands)
        if a.is_complex():
            a.set_data({"x": random.randint(0, 63), "y": random.randint(0, 63)})
        return a
