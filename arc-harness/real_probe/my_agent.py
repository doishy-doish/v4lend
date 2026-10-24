import random
from collections import Counter

from arcengine import FrameData, GameAction, GameState
from agents.agent import Agent


class MyAgent(Agent):
    MAX_ACTIONS = 200

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._frame_keys = None
        self._states_seen = []

    def is_done(self, frames, latest_frame):
        return latest_frame.state is GameState.WIN

    def choose_action(self, frames, latest_frame):
        if self._frame_keys is None:
            self._frame_keys = sorted([x for x in dir(latest_frame) if not x.startswith("_")])
        self._states_seen.append(str(latest_frame.state))
        if latest_frame.state in (GameState.NOT_PLAYED, GameState.GAME_OVER):
            return GameAction.RESET
        cands = [a for a in GameAction if a is not GameAction.RESET]
        a = random.choice(cands)
        if a.is_complex():
            a.set_data({"x": random.randint(0, 63), "y": random.randint(0, 63)})
        return a
