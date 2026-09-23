"""主 Agent：编排子 Agent 跑通一次申请闭环，并按流程节点推进"办理进度"。"""
from ..agents.collect_agent import CollectAgent
from ..agents.condition_agent import ConditionAgent
from ..agents.consult_agent import ConsultAgent
from ..agents.item_agent import ItemAgent
from ..agents.progress_agent import ProgressAgent
from ..agents.verify_agent import VerifyAgent
from ..materials.spec import (PASSED, material_names, material_specs, status_of,
                             summary)
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

    # ---------- 面向群众的自然语言文案（不出现 JSON / 内部 id / 模型名） ----------

    def _field_labels(self):
        return {spec["key"]: spec.get("label", spec["key"]) for spec in self.scenario["collect_fields"]}

    @staticmethod
    def _human(value):
        if value is True:
            return "是"
        if value is False:
            return "否"
        return str(value)

    def _describe_form(self, form):
        labels = self._field_labels()
        parts = []
        for key, value in form.fields.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            parts.append(labels.get(key, key) + "：" + self._human(value))
        if not parts:
            return "还没有收到您的申请信息。"
        return "已记录您的申请信息 —— " + "；".join(parts) + "。"

    def _material_names(self, material_ids):
        """材料 id -> 中文名（材料在场景配置里用稳定 id 存储，面向用户只出现中文名）。"""
        return material_names(self.scenario, material_ids)

    def _describe_plan(self, items, materials, notes):
        names = [self.scenario["items"].get(item, {}).get("name", item) for item in items]
        lines = ["根据您的情况，需要办理 " + str(len(names)) + " 件事：" + "、".join(names) + "。"]
        if notes:
            lines.append("其中：" + "；".join(notes) + "。")
        lines.append("需要准备 " + str(len(materials)) + " 份材料："
                     + "、".join(self._material_names(materials)) + "。")
        return "\n".join(lines)

    def _describe_materials(self, materials):
        return (
            "材料要求已确认，共 " + str(len(materials)) + " 份："
            + "、".join(self._material_names(materials))
            + "。下一步会逐项提示您提交。"
        )

    def _describe_submit(self, case, items):
        departments = []
        for item_id in items:
            dept = self.scenario["items"].get(item_id, {}).get("department")
            if dept and dept not in departments:
                departments.append(dept)
        return (
            "已受理，办理单号 " + case.case_id + "。已同时转交" + "、".join(departments)
            + "，并联办理，办好后通知您。"
        )

    def _describe_item(self, result):
        text = result["department"] + "已办结「" + result["name"] + "」"
        if result.get("output"):
            text += "，出件：" + result["output"]
        return text + "。"

    def _describe_progress(self, case):
        total = len(case.item_status)
        done = sum(1 for status in case.item_status.values() if status == "已办结")
        if total and done == total:
            return ("目前 " + str(total) + " 件事都已办结，办理单 " + case.case_id
                    + " 完成。每个环节的进度都能在进度看板里看到。")
        return ("办理单 " + case.case_id + " 正在办理：已办结 " + str(done) + "/" + str(total) + "。")

    def _on_item_done(self, trace, flow, case, result, on_event=None):
        """部门子 Agent 完成后的回调：更新事项状态与流程节点。"""
        item_id = result["item_id"]
        self.gov.finish(case, item_id, result["status"])
        detail = result["department"]
        if result.get("output"):
            detail += " · " + result["output"]
        flow.complete(item_id, detail)
        self._log(trace, on_event, "部门子Agent", self._describe_item(result))
        trace.append(("办理进度", flow.render_inline()))
        self._emit(on_event, ITEM_DONE, item_id=item_id, name=result["name"],
                   department=result["department"], output=result.get("output", ""),
                   status=result["status"])
        self._emit_node(on_event, flow, item_id)

    # ---------- 对外入口 ----------

    def run(self, utterance, answers=None, on_event=None, intake=None):
        """跑完整流程。on_event 可选（前端实时订阅用）；不传时行为与以往一致。

        `intake` 为材料收集单（见 app/materials）：传了就表示"材料已提交齐备"，
        跳过前四步，直接从「材料核验」续跑到办结。
        """
        answers = answers or {}
        try:
            return self._run(utterance, answers, on_event, intake)
        except Exception as exc:
            self._emit(on_event, ERROR, code=exc.__class__.__name__, message=str(exc))
            raise

    def _run(self, utterance, answers, on_event, intake=None):
        if intake is not None:
            return self._resume(intake, on_event)

        intent = route_intent(utterance)
        if intent == "query" and answers.get("case_id"):
            return self.query(answers["case_id"], on_event=on_event)

        trace = []
        flow = FlowProgress()

        # 1. 意图识别（智能路由）
        flow.start("intent")
        trace.append(("意图路由", "识别意图 -> " + intent))
        self._complete(trace, flow, "intent", "已了解您要办的事", on_event=on_event)

        # 2. 咨询
        flow.start("consult")
        self._log(trace, on_event, "咨询Agent", self.consult.answer(utterance, self.scenario))
        self._complete(trace, flow, "consult", "已说明办理要点与材料", on_event=on_event)

        # 3. 信息采集
        flow.start("collect")
        form = self.collect.collect(self.scenario["id"], self.scenario["collect_fields"], answers)
        self.context.set("form", form)
        self._log(trace, on_event, "信息采集Agent", self._describe_form(form))
        self._complete(trace, flow, "collect", "已记录申请信息", on_event=on_event)

        # 4. 条件判定（智能路由核心）
        flow.start("condition")
        items, materials, notes = self.condition.evaluate(self.scenario, form)
        self.context.set("items", items)
        self.context.set("materials", materials)
        self._log(trace, on_event, "条件判定Agent", self._describe_plan(items, materials, notes))
        self._complete(trace, flow, "condition", "已确定需办事项与材料", on_event=on_event)

        # 5. 材料核验
        flow.start("verify")
        report = self.verify.verify(materials)
        self._log(trace, on_event, "材料核验Agent", self._describe_materials(materials))
        self._complete(trace, flow, "verify", "已确认材料要求", on_event=on_event)

        return self._dispatch(trace, flow, items, materials, form, on_event)

    def _resume(self, intake, on_event):
        """材料已提交齐备后，从「材料核验」续跑到办结。

        材料清单在受理前就已确认（存在 intake 里），因此这里不重跑
        意图 / 咨询 / 采集 / 条件判定四步，只把它们标记为已完成，
        避免对话区把同样的内容再播报一遍。
        """
        trace = []
        flow = FlowProgress()
        for key, detail in (("intent", "已了解您要办的事"),
                            ("consult", "已说明办理要点与材料"),
                            ("collect", "已记录申请信息"),
                            ("condition", "已确定需办事项与材料")):
            flow.start(key)
            self._complete(trace, flow, key, detail, on_event=on_event)

        items = list(intake.items)
        material_ids = list(intake.materials)
        specs = material_specs(self.scenario, material_ids)

        # 受理前置条件：必交材料全部通过（服务端兜底，前端按钮禁用只是第一道）
        state = summary(specs, intake.files)
        if not state["ready"]:
            pending = [spec["name"] for spec in specs if spec.get("required", True)
                       and status_of(spec, intake.files_of(spec["id"])) != PASSED]
            raise ValueError("这些材料还没交齐或还没通过：" + "、".join(pending) + "。")

        # 5. 材料核验（用用户实际提交的文件）
        flow.start("verify")
        report = self.verify.review(specs, intake.files)
        self._log(trace, on_event, "材料核验Agent",
                  "材料已收齐 " + str(report["passed"]) + "/" + str(report["checked"])
                  + " 项，全部通过核验。")
        self._complete(trace, flow, "verify",
                       "材料 " + str(report["passed"]) + "/" + str(report["checked"]) + " 项通过",
                       on_event=on_event)

        return self._dispatch(trace, flow, items, material_ids, intake.form, on_event,
                              verify_report=dict(report))

    def _dispatch(self, trace, flow, items, materials, form, on_event, verify_report=None):
        """并联提交 -> 各部门办结 -> 进度落库（材料就绪后的公共尾段）。"""
        # 6. 并联提交：登记各部门事项节点，并联提交后由部门子 Agent 分别办理
        flow.start("submit")
        case = self.gov.submit(self.scenario["id"], items, materials, form,
                               verify_report=verify_report)
        for item_id in items:
            flow.add_node(item_id, self.scenario["items"].get(item_id, {}).get("name", item_id), before="track")
        self._log(trace, on_event, "主Agent", self._describe_submit(case, items))
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
        self._complete(trace, flow, "track", "进度已可随时查询", on_event=on_event)
        case.flow = flow.snapshot()
        case.updated_at = now()
        self.repo.save_case(case)
        trace.append(("办理进度看板", self._board(case)))  # 仅 CLI 展示，不进对话
        self._log(trace, on_event, "进度Agent", self._describe_progress(case))
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
