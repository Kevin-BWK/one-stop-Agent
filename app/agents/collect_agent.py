"""信息采集 Agent：按场景字段收集信息，生成结构化表单。"""
from app.models.schema import ApplicationForm
from .base import BaseAgent


class CollectAgent(BaseAgent):
    name = "collect"

    def collect(self, scenario_id, fields_spec, answers):
        data = {}
        for spec in fields_spec:
            key = spec["key"]
            value = answers.get(key)
            if value is None:
                value = spec.get("default", "")  # 桩：真实实现发起多轮追问
            data[key] = value
            self.context.set(key, value)
        return ApplicationForm(scenario_id=scenario_id, fields=data)
