"""
回填现有 GDGGZY 数据的 content 字段（从已有字段构建摘要）
无需 API 调用，直接从数据中已有字段生成摘要
"""
import json
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data" / "procurements.json"

with open(DATA_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

filled = 0
for item in data:
    if item.get("source") != "gdggzy":
        continue
    if item.get("content"):
        continue  # 已有正文，跳过

    # 从现有字段构建摘要
    parts = []
    if item.get("project_name"):
        parts.append(f"公告标题：{item['project_name']}")
    if item.get("hospital"):
        parts.append(f"采购人：{item['hospital']}")
    if item.get("project_no"):
        parts.append(f"项目编号：{item['project_no']}")
    if item.get("region"):
        parts.append(f"地区：{item['region']}")
    if item.get("publish_date"):
        parts.append(f"发布日期：{item['publish_date']}")
    if item.get("notice_type"):
        parts.append(f"公告类型：{item['notice_type']}")
    if item.get("raw_category"):
        parts.append(f"数据集：{item['raw_category']}")

    if parts:
        item["content"] = "\n".join(parts)
        filled += 1

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# 验证
gdggzy = [i for i in data if i.get("source") == "gdggzy"]
with_content = sum(1 for i in gdggzy if i.get("content"))
print(f"回填完成: {filled} 条 GDGGZY 数据")
print(f"GDGGZY 总计: {len(gdggzy)} 条, 有正文: {with_content} 条 ({100*with_content//max(len(gdggzy),1)}%)")

# 显示示例
for item in gdggzy[:2]:
    print(f"\n--- {item.get('project_name','')[:50]} ---")
    print(item.get('content', ''))
