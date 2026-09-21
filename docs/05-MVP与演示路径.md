# 05 MVP 与演示路径

## 运行方式

```bash
python run_demo.py               # 两个场景都跑
python run_demo.py restaurant    # 开办餐饮店
python run_demo.py enterprise    # 开办企业
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

- 政务系统用 `app/mock_gov/services.py` 模拟并联办理与进度。
- 知识库用 `data/knowledge/*.md`，检索为桩实现，后续替换为向量检索。
- MoMA 调用用 `app/moma/client.py` 桩，后续替换为真实 API。
