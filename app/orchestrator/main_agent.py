"""主 Agent：编排子 Agent 跑通一次申请闭环，并按流程节点推进"办理进度"。"""
from ..agents.collect_agent import CollectAgent
from ..agents.condition_agent import ConditionAgent
from ..agents.consult_agent import ConsultAgent
from ..agents.item_agent import ItemAgent
from ..agents.progress_agent import ProgressAgent
from ..agents.verify_agent import VerifyAgent
from .events import (CASE_CREATED, ERROR, FINISHED, FLOW_NODE, ITEM_DONE,
                     MESSAGE, Event)
from .flow import FlowProgress, now
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
        self.item = ItemAgent(moma, context)
        self.progress = ProgressAgent(moma, context)
        # 对齐历史办理单的单号序列，避免落盘后重号
        cases = self.repo.list_cases() if hasattr(self.repo, "list_cases") else []
        self.gov.sync_from(cases)

    # ---------- 事件出口：供 GUI 订阅，不传 on_event 时无任何副作用 ----------

    def _emit(self, on_event, event_type, **data):
        if on_event is not None:
            on_event(Event(event_type, data))

    def _emit_node(self, on_event, flow, key):
        data = dict(flow.node(key))
        data["done"] = flow.done_count()
        data["total"] = flow.total()
        self._emit(on_event, FLOW_NODE, **data)

    def _log(self, trace, on_event, stage, text):
        """记录编排轨迹；面向用户的文本同时作为 message 事件推送。"""
        trace.append((stage, text))
        self._emit(on_event, MESSAGE, stage=stage, text=text)

    def _complete(self, trace, flow, key, detail="", on_event=None):
        """节点办理完成即打勾，并把进度快照追加到编排轨迹、推送 flow_node 事件。"""
        flow.complete(key, detail)
        trace.append(("办理进度", flow.render_inline()))
        self._emit_node(on_event, flow, key)

    def _board(self, case):
        return self.progress.board(case.flow, case.item_status, self.scenario["items"])

    def _on_item_done(self, trace, flow, case, result, on_event=None):
        """部门子 Agent 完成后的回调：更新事项状态与流程节点。"""
        item_id = result["item_id"]
        self.gov.finish(case, item_id, result["status"])
        detail = result["department"]
        if result.get("output"):
            detail += " · " + result["output"]
        flow.complete(item_id, detail)
        self._log(trace, on_event, "部门子Agent",
                  result["department"] + "：" + result["name"] + " -> " + result["status"])
        trace.append(("办理进度", flow.render_inline()))
        self._emit(on_event, ITEM_DONE, item_id=item_id, name=result["name"],
                   department=result["department"], output=result.get("output", ""),
                   status=result["status"])
        self._emit_node(on_event, flow, item_id)

    # ---------- 对外入口 ----------

    def run(self, utterance, answers=None, on_event=None):
        """跑完整流程。on_event 可选（GUI 实时订阅用）；不传时行为与以往一致。"""
        answers = answers or {}
        try:
            return self._run(utterance, answers, on_event)
        except Exception as exc:
            self._emit(on_event, ERROR, code=exc.__class__.__name__, message=str(exc))
            raise

    def _run(self, utterance, answers, on_event):
        intent = route_intent(utterance)
        if intent == "query" and answers.get("case_id"):
            return self.query(answers["case_id"], on_event=on_event)

        trace = []
        flow = FlowProgress()

        # 1. 意图识别（智能路由）
        flow.start("intent")
        trace.append(("意图路由", "识别意图 -> " + intent))
        self._complete(trace, flow, "intent", "识别意图 -> " + intent, on_event=on_event)

        # 2. 咨询
        flow.start("consult")
        self._log(trace, on_event, "咨询Agent", self.consult.answer(utterance, self.scenario))
        self._complete(trace, flow, "consult", "已解答办事要点", on_event=on_event)

        # 3. 信息采集
        flow.start("collect")
        form = self.collect.collect(self.scenario["id"], self.scenario["collect_fields"], answers)
        self.context.set("form", form)
        self._log(trace, on_event, "信息采集Agent", "已生成一次申请表单：" + str(form.fields))
        self._complete(trace, flow, "collect", "已生成一次申请表单", on_event=on_event)

        # 4. 条件判定（智能路由核心）
        flow.start("condition")
        items, materials, notes = self.condition.evaluate(self.scenario, form)
        self.context.set("items", items)
        self.context.set("materials", materials)
        note_text = "；".join(notes) if notes else "无特殊条件"
        self._log(trace, on_event, "条件判定Agent",
                  "需办理事项：" + str(items) + "；材料：" + str(materials) + "。判定说明：" + note_text)
        self._complete(trace, flow, "condition", "已判定事项与材料", on_event=on_event)

        # 5. 材料核验
        flow.start("verify")
        report = self.verify.verify(materials)
        self._log(trace, on_event, "材料核验Agent", "核验结果：" + str(report))
        self._complete(trace, flow, "verify", "核验结果：" + str(report.get("status", "")), on_event=on_event)

        # 6. 并联提交：登记各部门事项节点，并联提交后由部门子 Agent 分别办理
        flow.start("submit")
        case = self.gov.submit(self.scenario["id"], items, materials, form)
        for item_id in items:
            flow.add_node(item_id, self.scenario["items"].get(item_id, {}).get("name", item_id), before="track")
        self._log(trace, on_event, "主Agent", "已生成办理单 " + case.case_id + "，并联提交至各部门")
        self._complete(trace, flow, "submit", "办理单 " + case.case_id, on_event=on_event)
        self._emit(on_event, CASE_CREATED, case_id=case.case_id, scenario_id=case.scenario_id,
                   items=list(case.items), materials=list(case.materials))

        # 7. 各部门并联办理：每个事项交给部门子 Agent，完成后回调主 Agent 更新流程节点
        def on_done(result):
            self._on_item_done(trace, flow, case, result, on_event=on_event)

        for item_id in items:
            meta = self.scenario["items"].get(item_id, {})
            flow.start(item_id)
            self.gov.start(case, item_id)
            self.item.process(item_id, meta, on_done=on_done)

        # 8. 进度跟踪：流程台账写入办理单并落库，供后续按单号查询
        flow.start("track")
        self._complete(trace, flow, "track", "进度看板已生成", on_event=on_event)
        case.flow = flow.snapshot()
        case.updated_at = now()
        self.repo.save_case(case)
        self._log(trace, on_event, "进度Agent", "当前进度：\n" + self._board(case))
        self._emit(on_event, FINISHED, case_id=case.case_id, flow=case.flow,
                   item_status=dict(case.item_status))

        return trace, case

    def query(self, case_id, on_event=None):
        """按办理单号查询进度看板（只读）。"""
        trace = [("意图路由", "识别意图 -> query")]
        case = self.repo.get_case(case_id)
        self.context.set("case_id", case_id)
        if case is None:
            self._log(trace, on_event, "进度Agent", "未找到办理单 " + str(case_id) + "，请核对单号。")
            return trace, None
        self._log(trace, on_event, "进度Agent", "当前进度：\n" + self._board(case))
        return trace, case
