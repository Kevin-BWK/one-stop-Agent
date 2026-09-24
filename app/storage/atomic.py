"""JSON 落盘的原子写：先写同目录临时文件，再 `os.replace` 覆盖。

解决的是 `docs/10` 第 4 条里"整文件读写、多进程互相覆盖"的一半问题：
`os.replace` 在同一文件系统上是原子操作，读方**永远看不到半截 JSON**
（此前直接 `write_text`，进程被中断会留下损坏文件）。

注意：原子写只保证"不写坏"，**不保证并发不丢更新**——真正多进程并发
仍需 Redis / 数据库（见 `app/storage/base.py` 的接口与 `docs/12`）。
"""
import json
import os
import uuid
from pathlib import Path
from typing import Any


def write_json(path, payload: Any) -> None:
    """把 `payload` 以 UTF-8 JSON 原子写入 `path`。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp" + uuid.uuid4().hex[:8])
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def read_json(path, default: Any = None) -> Any:
    """读取 JSON；文件不存在或损坏时返回 `default`（宁可空启动也不崩）。"""
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default
