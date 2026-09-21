"""主 Agent：编排子 Agent，跑通一次申请闭环。"""
from ..models.schema import CaseRecord
from ..agents.consult_agent import ConsultAgent
from ..agents.collect_agent import CollectAgent
from ..agents.condition_agent import ConditionAgent
from ..agents.verify_agent import VerifyAgent
from ..agents.progress_agent import ProgressAgent
from .router import route_intent


class MainAgent:
    def __init__(self, scenario, moma, knowledge, gov, repo, context):
        self.scenario = scenario
        self.moma = moma
        self.knowledge = knowledge
        self.gov = gov
        self.repo = repo
        self.context = context
        self.consult = ConsultAgent(moma, context)
        self.collect = CollectAgent(moma, context)
        self.condition = ConditionAgent(moma, context)
        self.verify = VerifyAgent(moma, context)
        self.progress = ProgressAgent(moma, context)

    def run(self, utterance, answers=None):
        answers = answers or {}
        trace = []

        # 1. 意图识别（智能路由）
        intent = route_intent(utterance)
        trace.append(("意图路由", "识别意图 -> " + intent))

        # 2. 咨询
        trace.append(("咨询Agent", self.consult.answer(utterance, self.scenario)))

        # 3. 信息采集
        form = self.collect.collect(self.scenario["id"], self.scenario["collect_fields"], answers)
        self.context.set("form", form)
        trace.append(("信息采集Agent", "已生成一次申请表单：" + str(form.fields)))

        # 4. 条件判定（智能路由核心）
        items, materials, notes = self.condition.evaluate(self.scenario, form)
        self.context.set("items", items)
        self.context.set("materials", materials)
        note_text = "；".join(notes) if notes else "无特殊条件"
        trace.append(("条件判定Agent", "需办理事项：" + str(items) + "；材料：" + str(materials) + "。判定说明：" + note_text))

        # 5. 材料核验
        report = self.verify.verify(materials)
        trace.append(("材料核验Agent", "核验结果：" + str(report)))

        # 6. 并联提交
        case = self.gov.submit(self.scenario["id"], items, materials, form)
        self.repo.save_case(case)
        trace.append(("主Agent", "已生成办理单 " + case.case_id + "，并联提交至各部门"))

        # 7. 进度查询
        progress_text = self.progress.query(case.item_status, self.scenario["items"])
        trace.append(("进度Agent", "当前进度：\n" + progress_text))

        return trace, case
