"""内存存储：骨架阶段用字典，后续可换数据库。"""


class InMemoryRepo:
    def __init__(self):
        self._cases = {}

    def save_case(self, case):
        self._cases[case.case_id] = case

    def get_case(self, case_id):
        return self._cases.get(case_id)
