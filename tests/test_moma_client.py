"""MoMA 客户端测试：桩模式 / 真实模式 / 重试 / 错误处理 / 模型覆盖。

全部离线运行（注入 FakeSession），不需要真实网络或密钥。
用法：python tests/test_moma_client.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents.consult_agent import ConsultAgent
from app.moma.client import MoMAAPIError, MoMAClient
from app.moma.context import SessionContext

SCENARIO = {
    "id": "restaurant_open",
    "name": "开办餐饮店一件事",
    "items": {"A_license": {"name": "个体工商户设立登记", "department": "市场监管"}},
    "base_materials": ["身份证"],
}


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """替代 requests 会话：按顺序返回预设响应，并记录调用参数。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(content):
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def no_sleep(_seconds):
    return None


def test_stub_mode():
    client = MoMAClient(api_base="", api_key="")
    assert client.mode() == "stub" and client.live is False
    assert client.dispatch("consult") == "deepseek-r1"
    assert client.complete("deepseek-r1", [{"role": "user", "content": "hi"}], fallback="FB") == "FB"
    assert client.chat("qwen-turbo", [{"role": "user", "content": "你好"}]) == "[qwen-turbo] 你好"


def test_live_mode_parse_openai():
    session = FakeSession([ok("真实回复")])
    client = MoMAClient(api_base="https://moma.example.com/v1/", api_key="k", session=session, sleep=no_sleep)
    assert client.mode() == "live"
    assert client.chat("deepseek-r1", [{"role": "user", "content": "你好"}]) == "真实回复"
    call = session.calls[0]
    assert call["url"] == "https://moma.example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["json"]["model"] == "deepseek-r1"
    assert call["timeout"] == 30.0


def test_retry_then_success():
    session = FakeSession([FakeResponse(500, text="boom"), ok("第二次成功")])
    client = MoMAClient(api_base="https://x/v1", api_key="k", max_retries=2, session=session, sleep=no_sleep)
    assert client.chat("m", [{"role": "user", "content": "hi"}]) == "第二次成功"
    assert len(session.calls) == 2


def test_network_error_retries_then_raises():
    session = FakeSession([ConnectionError("net"), ConnectionError("net"), ConnectionError("net")])
    client = MoMAClient(api_base="https://x/v1", api_key="k", max_retries=2, session=session, sleep=no_sleep)
    try:
        client.chat("m", [{"role": "user", "content": "hi"}])
        raise AssertionError("应当抛出 MoMAAPIError")
    except MoMAAPIError:
        pass
    assert len(session.calls) == 3


def test_4xx_no_retry_and_fallback():
    session = FakeSession([FakeResponse(401, text="unauthorized")])
    client = MoMAClient(api_base="https://x/v1", api_key="k", max_retries=2, session=session, sleep=no_sleep)
    try:
        client.chat("m", [{"role": "user", "content": "hi"}])
        raise AssertionError("4xx 应当直接失败")
    except MoMAAPIError:
        pass
    assert len(session.calls) == 1, "4xx 不应重试"

    session2 = FakeSession([FakeResponse(400, text="bad")])
    client2 = MoMAClient(api_base="https://x/v1", api_key="k", session=session2, sleep=no_sleep)
    assert client2.complete("m", [{"role": "user", "content": "hi"}], fallback="FB") == "FB"


def test_bad_json_raises():
    session = FakeSession([FakeResponse(200, None, text="not json")])
    client = MoMAClient(api_base="https://x/v1", api_key="k", session=session, sleep=no_sleep)
    try:
        client.chat("m", [{"role": "user", "content": "hi"}])
        raise AssertionError("非法 JSON 应当抛出 MoMAAPIError")
    except MoMAAPIError:
        pass


def test_model_env_override():
    os.environ["MOMA_MODEL_STRONG"] = "my-strong"
    try:
        client = MoMAClient(api_base="", api_key="")
        assert client.dispatch("consult") == "my-strong"
    finally:
        os.environ.pop("MOMA_MODEL_STRONG", None)


def test_consult_agent_wiring():
    # 桩模式 -> 本地固定人话兜底：按问题作答，且不出现模型名（见 docs/08 文案规范）
    stub = ConsultAgent(MoMAClient(api_base="", api_key=""), SessionContext())
    reply = stub.answer("需要什么材料", SCENARIO)
    assert "身份证" in reply, reply
    assert "[" not in reply and "]" not in reply, reply

    # 真实模式 -> 使用模型回复，且系统提示带上场景信息
    session = FakeSession([ok("模型回答")])
    live = ConsultAgent(
        MoMAClient(api_base="https://x/v1", api_key="k", session=session, sleep=no_sleep),
        SessionContext(),
    )
    assert live.answer("需要什么材料", SCENARIO) == "模型回答"
    sent = session.calls[0]["json"]["messages"]
    assert sent[0]["role"] == "system" and "开办餐饮店" in sent[0]["content"]


def test_consult_agent_multi_turn_context():
    """多轮上下文：本会话之前的问答要进入发给模型的消息（见 docs/08）。"""
    context = SessionContext()
    context.add_history("user", "开餐饮店要交什么材料")
    context.add_history("assistant", "要交身份证、经营场所证明。")

    session = FakeSession([ok("第二个问题的回答")])
    agent = ConsultAgent(
        MoMAClient(api_base="https://x/v1", api_key="k", session=session, sleep=no_sleep),
        context,
    )
    assert agent.answer("那第二个呢", SCENARIO) == "第二个问题的回答"

    sent = session.calls[0]["json"]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"], sent
    assert sent[1]["content"] == "开餐饮店要交什么材料", sent
    assert sent[-1]["content"] == "那第二个呢", sent        # 当前问题在最后，且不重复
    # 本轮问答也要记进历史，供下一轮使用
    assert context.history()[-2:] == [
        {"role": "user", "content": "那第二个呢"},
        {"role": "assistant", "content": "第二个问题的回答"},
    ], context.history()


def test_consult_agent_history_is_capped():
    """历史过长时只带最近若干条，避免请求无限膨胀、模型被早期内容带偏。"""
    context = SessionContext()
    for index in range(20):
        context.add_history("user", "问题" + str(index))
        context.add_history("assistant", "回答" + str(index))

    session = FakeSession([ok("ok")])
    agent = ConsultAgent(
        MoMAClient(api_base="https://x/v1", api_key="k", session=session, sleep=no_sleep),
        context,
    )
    agent.answer("最后的问题", SCENARIO)

    sent = session.calls[0]["json"]["messages"]
    assert len(sent) == 1 + ConsultAgent.MAX_HISTORY + 1, len(sent)
    assert sent[0]["role"] == "system"
    assert sent[-1]["content"] == "最后的问题"


def main():
    test_stub_mode()
    test_live_mode_parse_openai()
    test_retry_then_success()
    test_network_error_retries_then_raises()
    test_4xx_no_retry_and_fallback()
    test_bad_json_raises()
    test_model_env_override()
    test_consult_agent_wiring()
    test_consult_agent_multi_turn_context()
    test_consult_agent_history_is_capped()
    print("MOMA TESTS PASSED")


if __name__ == "__main__":
    main()