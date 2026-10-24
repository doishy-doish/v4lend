class BuilderGate:
    def __init__(self, threshold=0.5, patience=3):
        self.threshold = threshold
        self.patience = patience
        self.stuck = 0
        self.requests = 0

    def observe(self, err, progressed):
        if err >= self.threshold and not progressed:
            self.stuck += 1
        else:
            self.stuck = 0
        return self.stuck >= self.patience

    def request_builder(self):
        self.requests += 1
        self.stuck = 0
        return True
