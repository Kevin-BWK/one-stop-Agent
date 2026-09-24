"""材料提交 HTTP 接口（受理前的材料清单与上传通道）。

对应流程的第 ① ② 步（见 docs/09）：

    POST /api/materials/intake                        填完信息 -> 产出材料清单
    GET  /api/materials/{intake_id}                   取材料清单与各项状态
    POST /api/materials/{intake_id}/{material_id}/files       上传一张（multipart）
    DELETE /api/materials/{intake_id}/{material_id}/files/{file_id}  撤回一张
    GET  /api/materials/{intake_id}/{material_id}/files/{file_id}    读回文件（缩略图）

上传走 multipart/form-data，前端用 `uni.uploadFile` 即可跨端（H5 选文件、App 拍照）。
桩阶段文件落到 `data/runtime/materials/`，真实阶段换成对象存储，接口不变。

**鉴权（见 docs/10 第 5 条 / docs/12）**：材料是敏感个人信息，所有接口都做归属校验，
读取文件还要么是**绑定到该文件的短时签名链接**（图片要直接当 `<image src>`，
没法自定义请求头，`MaterialService` 会把它签进 URL），要么是**归属人本人**的登录令牌。
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.auth.models import User
from app.auth.service import AuthService
from app.materials.service import MaterialService
from app.materials.store import get_store

from .auth import ensure_access, make_user_dependency, resolve_user
from .schemas import IntakeRequest, MaterialViewOut


def build_router(service: Optional[MaterialService] = None,
                 auth: Optional[AuthService] = None) -> APIRouter:
    material_service = service or MaterialService(store=get_store())
    auth_service = auth or AuthService()
    current_user = make_user_dependency(auth_service)
    router = APIRouter(prefix="/api/materials", tags=["materials"])

    def _scenario_of(intake_id: str, intake) -> Dict[str, Any]:
        from .stream import load_scenario

        scenario = load_scenario(intake.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在：" + intake.scenario_id)
        return scenario

    def _intake_or_404(intake_id: str):
        intake = material_service.store.get(intake_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="材料受理号不存在：" + intake_id)
        return intake

    def _owned_intake(intake_id: str, user: User):
        """取收集单并校验归属（材料属敏感个人信息，见 docs/10 第 5 条）。"""
        intake = _intake_or_404(intake_id)
        ensure_access(user, intake.owner_id, permission="material:any")
        return intake

    def _payload(scenario: Dict[str, Any], intake, message: str = "") -> Dict[str, Any]:
        payload = material_service.view(scenario, intake)
        payload["message"] = message
        return payload

    @router.post("/intake", response_model=MaterialViewOut)
    def create_intake(req: IntakeRequest, user: User = Depends(current_user)):
        """按申请信息判定所需材料，开一张材料收集单（归属当前用户）。"""
        from .stream import load_scenario, missing_required

        scenario = load_scenario(req.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        missing = missing_required(scenario, req.answers)
        if missing:
            raise HTTPException(status_code=400, detail="还缺这些必填信息：" + "、".join(missing))

        intake = material_service.plan(scenario, req.answers, owner_id=user.user_id)
        head = ("根据您的情况，需要提交 " + str(len(intake.materials)) + " 份材料，"
                "材料没通过前无法受理。")
        return _payload(scenario, intake, message=head + "\n\n" + material_service.brief(scenario, intake))

    @router.get("/{intake_id}", response_model=MaterialViewOut)
    def get_intake(intake_id: str, user: User = Depends(current_user)):
        intake = _owned_intake(intake_id, user)
        scenario = _scenario_of(intake_id, intake)
        return _payload(scenario, intake)

    @router.post("/{intake_id}/{material_id}/files", response_model=MaterialViewOut)
    async def upload_file(intake_id: str, material_id: str,
                          file: UploadFile = File(...), slot: str = Form(""),
                          user: User = Depends(current_user)):
        intake = _owned_intake(intake_id, user)
        scenario = _scenario_of(intake_id, intake)
        content = await file.read()
        try:
            return material_service.upload(
                scenario, intake, material_id,
                filename=file.filename or "", content_type=file.content_type or "",
                content=content, slot=slot,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'\""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.delete("/{intake_id}/{material_id}/files/{file_id}", response_model=MaterialViewOut)
    def remove_file(intake_id: str, material_id: str, file_id: str,
                    user: User = Depends(current_user)):
        intake = _owned_intake(intake_id, user)
        scenario = _scenario_of(intake_id, intake)
        try:
            return material_service.remove(scenario, intake, material_id, file_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'\""))

    @router.get("/{intake_id}/{material_id}/files/{file_id}")
    def read_file(intake_id: str, material_id: str, file_id: str, request: Request,
                  token: str = ""):
        """读回一张材料文件。

        两条合法路径：
        1. URL 带**绑定到该文件的短时签名**（`?token=...`）——供 `<image src>` 使用；
        2. 请求带**归属人本人**（或工作人员）的登录令牌。

        两者都不满足则 401 / 403，避免"谁知道 URL 谁就能下载身份证照片"。
        """
        store = material_service.store
        intake = store.get(intake_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="材料受理号不存在：" + intake_id)

        signed = bool(token) and auth_service.verify_file_token(
            token, intake_id, material_id, file_id) is not None
        if not signed:
            user = resolve_user(request, auth_service)
            if user is None:
                raise HTTPException(status_code=401, detail="请先登录或使用带签名的文件链接")
            ensure_access(user, intake.owner_id, permission="material:any")

        _, record = store.find(intake_id, material_id, file_id)
        if record is None:
            raise HTTPException(status_code=404, detail="找不到这张文件")
        path = store.path_of(intake, material_id, file_id)
        if path is None:
            raise HTTPException(status_code=404, detail="文件已丢失，请重新上传")
        return FileResponse(path, media_type=record.content_type or "application/octet-stream",
                            filename=record.filename)

    return router
