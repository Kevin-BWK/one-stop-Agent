"""材料提交 HTTP 接口（受理前的材料清单与上传通道）。

对应流程的第 ① ② 步（见 docs/09）：

    POST /api/materials/intake                        填完信息 -> 产出材料清单
    GET  /api/materials/{intake_id}                   取材料清单与各项状态
    POST /api/materials/{intake_id}/{material_id}/files       上传一张（multipart）
    DELETE /api/materials/{intake_id}/{material_id}/files/{file_id}  撤回一张
    GET  /api/materials/{intake_id}/{material_id}/files/{file_id}    读回文件（缩略图）

上传走 multipart/form-data，前端用 `uni.uploadFile` 即可跨端（H5 选文件、App 拍照）。
桩阶段文件落到 `data/runtime/materials/`，真实阶段换成对象存储，接口不变。
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.materials.service import MaterialService
from app.materials.store import get_store

from .schemas import IntakeRequest, MaterialViewOut


def build_router(service: Optional[MaterialService] = None) -> APIRouter:
    material_service = service or MaterialService(store=get_store())
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

    def _payload(scenario: Dict[str, Any], intake, message: str = "") -> Dict[str, Any]:
        payload = material_service.view(scenario, intake)
        payload["message"] = message
        return payload

    @router.post("/intake", response_model=MaterialViewOut)
    def create_intake(req: IntakeRequest):
        """按申请信息判定所需材料，开一张材料收集单。"""
        from .stream import load_scenario, missing_required

        scenario = load_scenario(req.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="场景不存在")
        missing = missing_required(scenario, req.answers)
        if missing:
            raise HTTPException(status_code=400, detail="还缺这些必填信息：" + "、".join(missing))

        intake = material_service.plan(scenario, req.answers)
        head = ("根据您的情况，需要提交 " + str(len(intake.materials)) + " 份材料，"
                "材料没通过前无法受理。")
        return _payload(scenario, intake, message=head + "\n\n" + material_service.brief(scenario, intake))

    @router.get("/{intake_id}", response_model=MaterialViewOut)
    def get_intake(intake_id: str):
        intake = _intake_or_404(intake_id)
        scenario = _scenario_of(intake_id, intake)
        return _payload(scenario, intake)

    @router.post("/{intake_id}/{material_id}/files", response_model=MaterialViewOut)
    async def upload_file(intake_id: str, material_id: str,
                          file: UploadFile = File(...), slot: str = Form("")):
        intake = _intake_or_404(intake_id)
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
    def remove_file(intake_id: str, material_id: str, file_id: str):
        intake = _intake_or_404(intake_id)
        scenario = _scenario_of(intake_id, intake)
        try:
            return material_service.remove(scenario, intake, material_id, file_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'\""))

    @router.get("/{intake_id}/{material_id}/files/{file_id}")
    def read_file(intake_id: str, material_id: str, file_id: str):
        store = material_service.store
        intake, record = store.find(intake_id, material_id, file_id)
        if intake is None:
            raise HTTPException(status_code=404, detail="材料受理号不存在：" + intake_id)
        if record is None:
            raise HTTPException(status_code=404, detail="找不到这张文件")
        path = store.path_of(intake, material_id, file_id)
        if path is None:
            raise HTTPException(status_code=404, detail="文件已丢失，请重新上传")
        return FileResponse(path, media_type=record.content_type or "application/octet-stream",
                            filename=record.filename)

    return router
