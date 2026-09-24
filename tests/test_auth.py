"""多用户与鉴权测试（见 `docs/12`）。

覆盖四层：

1. **口令 / 令牌基元**：PBKDF2 口令哈希与校验、HMAC 自包含令牌的签名 / 篡改 / 过期；
2. **鉴权服务**：注册 / 登录 / 令牌解析 / 材料文件的绑定签名链接；
3. **HTTP 多用户隔离**：A 的会话 / 材料 / 办理单 B 一律拿不到（401 / 403），
   材料文件"带签名链接可读、无凭证不可读、别人的令牌不可读"；
4. **向后兼容**：`AUTH_REQUIRED` 未开启时未登录请求按演示用户处理，单用户 Demo 行为不变。

依赖：pip install -r requirements.txt httpx
用法：python tests/test_auth.py
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MOMA_DISABLE_LIVE", "1")  # 测试离线运行，避免真实调用

from fastapi.testclient import TestClient

from app.auth.models import ROLE_ADMIN, ROLE_STAFF, User
from app.auth.security import Signer, hash_password, verify_password
from app.auth.service import AuthService
from app.auth.store import InMemoryUserStore
from app.storage.factory import build_storage
from server.main import create_app

RESTAURANT = {
    "name": "老张牛肉面",
    "business_type": "热食/有油烟",
    "area_sqm": 80,
    "has_raw_food": False,
    "address": "幸福路 12 号",
    "signboard": True,
}

# 造一张体积正常（核验通过）的图片
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * (20 * 1024 - 4)


def bearer(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


# ---------------------------------------------------------------- 1. 基元

def test_password_hashing():
    stored = hash_password("s3cret-pw")
    assert stored.startswith("pbkdf2_sha256$")
    assert "s3cret-pw" not in stored                       # 永不落明文
    assert hash_password("s3cret-pw") != stored            # 每次盐不同
    assert verify_password("s3cret-pw", stored) is True
    assert verify_password("wrong", stored) is False
    assert verify_password("s3cret-pw", "不是哈希") is False      # 非法输入不抛异常
    assert verify_password("s3cret-pw", "") is False


def test_token_signing_and_expiry():
    signer = Signer("unit-secret")
    token = signer.sign({"sub": "u_1", "typ": "session", "exp": int(time.time()) + 60})
    assert signer.verify(token)["sub"] == "u_1"
    assert signer.verify(token + "x") is None              # 篡改签名
    assert signer.verify("garbage") is None
    assert Signer("another-secret").verify(token) is None  # 换密钥即失效

    expired = signer.sign({"sub": "u_1", "typ": "session", "exp": int(time.time()) - 1})
    assert signer.verify(expired) is None


# ---------------------------------------------------------------- 2. 鉴权服务

def test_auth_service_flow():
    auth = AuthService(store=InMemoryUserStore(), secret="svc-secret", required=False)

    user = auth.register("alice", "secret1", display_name="爱丽丝")
    assert user.user_id.startswith("u_") and user.role == "applicant"
    try:
        auth.register("alice", "secret2")
        raise AssertionError("重名用户名应被拒绝")
    except ValueError:
        pass
    try:
        auth.register("bob", "123")
        raise AssertionError("过短口令应被拒绝")
    except ValueError:
        pass

    assert auth.login("alice", "secret1").user_id == user.user_id
    for bad in (("alice", "nope"), ("ghost", "secret1")):
        try:
            auth.login(*bad)
            raise AssertionError("错误凭据应登录失败")
        except KeyError:
            pass

    token = auth.issue_token(user)
    assert auth.resolve(token).user_id == user.user_id
    assert auth.resolve(token + "x") is None
    assert auth.resolve("") is None

    # 文件签名链接：绑定到具体文件，不能挪作他用
    file_token = auth.issue_file_token(user.user_id, "CL0001", "id_card", "abc123")
    assert auth.verify_file_token(file_token, "CL0001", "id_card", "abc123") == user.user_id
    assert auth.verify_file_token(file_token, "CL0001", "id_card", "other") is None
    assert auth.verify_file_token(file_token, "CL9999", "id_card", "abc123") is None
    assert auth.verify_file_token("bogus", "CL0001", "id_card", "abc123") is None


def test_user_rbac_semantics():
    applicant = User("u_a", "a", role="applicant")
    staff = User("u_s", "s", role=ROLE_STAFF)
    admin = User("u_admin", "admin", role=ROLE_ADMIN)

    # 空归属（历史 / 演示数据）不设限；自己的数据永远可访问
    assert applicant.can_access("")
    assert applicant.can_access("u_a")
    assert not applicant.can_access("u_b")            # 别人的数据不行
    assert staff.can_access("u_b", "case:any")        # 工作人员可跨用户查办理单
    assert not staff.can_access("u_b", "material:any")
    assert admin.can_access("whoever", "material:any")


# ---------------------------------------------------------------- 3. HTTP 多用户

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_http_multi_user_isolation():
    storage = build_storage("memory")
    auth = AuthService(store=storage.users, secret="http-secret", required=True)
    client = TestClient(create_app(storage=storage, auth=auth))

    # 强制登录：健康检查应如实反映形态
    health = client.get("/health").json()
    assert health["storage"] == "memory" and health["auth_required"] is True, health

    # 未登录：所有需要用户上下文的接口一律 401
    assert client.post("/api/session", json={"scenario_id": "restaurant_open"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/materials/CL0001").status_code == 401

    # 注册：接口不接受自定义角色（防提权），重名 400
    for name in ("alice", "bob"):
        r = client.post("/api/auth/register", json={"username": name, "password": "secret1"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "applicant", r.json()
    assert client.post("/api/auth/register",
                       json={"username": "alice", "password": "secret1"}).status_code == 400
    assert client.post("/api/auth/login",
                       json={"username": "alice", "password": "bad"}).status_code == 401

    alice, bob = _login(client, "alice", "secret1"), _login(client, "bob", "secret1")
    a_head, b_head = bearer(alice), bearer(bob)
    assert client.get("/api/auth/me", headers=a_head).json()["username"] == "alice"

    # alice 建会话；bob 碰不到
    r = client.post("/api/session", json={"scenario_id": "restaurant_open"}, headers=a_head)
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert client.get("/api/sessions/" + sid, headers=b_head).status_code == 403
    assert client.post("/api/chat", json={"session_id": sid, "message": "进度"},
                       headers=b_head).status_code == 403

    # 采齐字段 -> 产出材料清单（尚未受理）
    t = client.post("/api/chat", json={"session_id": sid, "message": "我想开一家牛肉面馆"},
                    headers=a_head).json()
    guard = 0
    while t.get("next_question"):
        q = t["next_question"]
        t = client.post("/api/fields", json={"session_id": sid, "key": q["key"],
                                             "value": RESTAURANT[q["key"]]},
                        headers=a_head).json()
        guard += 1
        assert guard < 20
    assert t.get("intake_id") and t.get("case") is None, t
    intake_id = t["intake_id"]

    # bob 拿不到、也传不了 alice 的材料
    assert client.get("/api/materials/" + intake_id, headers=b_head).status_code == 403
    r = client.post("/api/materials/" + intake_id + "/id_card/files",
                    files={"file": ("a.jpg", JPG, "image/jpeg")}, data={"slot": "正面"},
                    headers=b_head)
    assert r.status_code == 403, r.text

    # alice 传齐材料
    first_file_url = ""
    for material in t["material_view"]["materials"]:
        for slot in (material["slots"] or [""]):
            r = client.post(
                "/api/materials/" + intake_id + "/" + material["id"] + "/files",
                files={"file": ((slot or material["id"]) + ".jpg", JPG, "image/jpeg")},
                data={"slot": slot}, headers=a_head)
            assert r.status_code == 200, r.text
            if not first_file_url:
                first_file_url = r.json()["materials"][0]["files"][0]["url"]
    # 材料 URL 带绑定该文件的短时签名（图片要能直接当 <image src> 用）
    assert "?token=" in first_file_url, first_file_url
    file_path, file_token = first_file_url.split("?token=")

    # 文件读取：带签名链接可读；无凭证 / 篡改签名 401；别人的令牌 403
    assert client.get(first_file_url).status_code == 200          # 签名链接，无需请求头
    assert client.get(file_path).status_code == 401
    assert client.get(file_path + "?token=forged").status_code == 401
    assert client.get(file_path, headers=a_head).status_code == 200
    assert client.get(file_path, headers=b_head).status_code == 403

    # 受理并跑编排：办理单归属 alice
    r = client.get("/apply", params={
        "scenario_id": "restaurant_open", "utterance": "我想开一家牛肉面馆",
        "answers": json.dumps(RESTAURANT, ensure_ascii=False),
        "intake_id": intake_id, "session_id": sid}, headers=a_head)
    assert r.status_code == 200 and "event: finished" in r.text, r.text
    case_id = client.get("/api/sessions/" + sid, headers=a_head).json()["case"]["case_id"]

    # 办理单：本人可读，别人 403
    case = client.get("/api/cases/" + case_id, headers=a_head)
    assert case.status_code == 200 and case.json()["owner_id"], case.text
    assert client.get("/api/cases/" + case_id, headers=b_head).status_code == 403

    # 工作人员：跨用户可查办理单，但拿不到会话 / 材料
    staff = auth.register("staff1", "secret1", role=ROLE_STAFF)
    s_head = bearer(auth.issue_token(staff))
    assert client.get("/api/cases/" + case_id, headers=s_head).status_code == 200
    assert client.get("/api/sessions/" + sid, headers=s_head).status_code == 403
    assert client.get("/api/materials/" + intake_id, headers=s_head).status_code == 403


# ---------------------------------------------------------------- 4. 向后兼容

def test_demo_mode_without_auth():
    """AUTH_REQUIRED 未开启：未登录 = 演示用户，单用户 Demo 行为不变。"""
    client = TestClient(create_app(storage=build_storage("memory"),
                                   auth=AuthService(store=InMemoryUserStore(),
                                                    secret="demo-secret", required=False)))
    assert client.get("/health").json()["auth_required"] is False

    r = client.post("/api/session", json={"scenario_id": "restaurant_open"})
    assert r.status_code == 200, r.text                    # 不带令牌也能用
    sid = r.json()["session_id"]
    assert client.get("/api/sessions/" + sid).status_code == 200
    assert client.get("/api/auth/me").json()["user_id"] == "u_demo"

    # 但携带了"无效令牌"时不静默降级，避免令牌过期被当成演示用户混过去
    assert client.get("/api/auth/me", headers=bearer("expired-or-forged")).status_code == 401


def main():
    test_password_hashing()
    test_token_signing_and_expiry()
    test_auth_service_flow()
    test_user_rbac_semantics()
    test_http_multi_user_isolation()
    test_demo_mode_without_auth()
    print("AUTH TESTS PASSED")


if __name__ == "__main__":
    main()
