"""上下文管理：全局会话上下文，供多个 Agent 共享。"""


class SessionContext:
    def __init__(self):
        self._data = {}
        self._history = []

    def set(self, key, value):
        self._data[key] = value

    def get(self, key, default=None):
        return self._data.get(key, default)

    def add_history(self, role, content):
        self._history.append({"role": role, "content": content})

    def history(self):
        return list(self._history)

    def snapshot(self):
        return dict(self._data)
