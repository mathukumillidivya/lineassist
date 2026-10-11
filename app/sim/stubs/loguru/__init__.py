"""Stand-in for loguru: the simulator only logs, and the browser has nowhere to put it."""


class _Logger:
    def __getattr__(self, name):
        return lambda *a, **k: None


logger = _Logger()
