# 05 MVP 与演示路径

## 运行方式

```bash
python run_demo.py               # 两个场景都跑，并演示并联办理进度推进
python run_demo.py restaurant    # 开办餐饮店
python run_demo.py enterprise    # 开办企业
python run_demo.py --query YJS0001   # 按办理单号查询办理进度看板
python tests/test_flow.py        # 冒烟测试
```

## 演示路径（餐饮店）

1. 标准路径（牛肉面馆，热食 + 小面积 + 招牌）：触发油烟净化 + 招牌审批。
2. 无油烟路径（奶茶店）：不触发油烟净化，材料更少。
3. 复杂路径（大面积烧烤店，面积 >= 300㎡）：额外触发消防检查。

## 演示路径（企业）

1. 标准路径：设立登记 + 税务 + 社保 + 公章刻制。
2. 加开户路径（need_bank=true）：额外增加银行开户预约。
3. 加用工路径（employees >= 10）：额外增加用工备案材料。

## 数据模拟

- 政务系统用 `app/mock_gov/services.py` 模拟并联办理；各部门事项由子 Agent 办结后回调主 Agent 更新进度。
- 办理单与进度用 `app/storage/repo.py` 的 `JsonFileRepo` 落盘到 `data/runtime/cases.json`，支持按单号跨进程查询。
- 知识库用 `data/knowledge/*.md`，检索为桩实现，后续替换为向量检索。
- MoMA 调用用 `app/moma/client.py` 桩，后续替换为真实 API。
