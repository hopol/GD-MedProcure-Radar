#!/usr/bin/env python3
"""
粤采雷达 - 搜索索引与聚合数据构建
===================================
功能:
  1. 读取 data/procurements.json
  2. 生成 data/aggregations.json  — 地区/类目/统计聚合（前端筛选用）
  3. 生成 frontend/public/search-index.json — FlexSearch 兼容索引
  4. 复制 procurements.json → frontend/public/data/procurements.json

用法:
  python scripts/build_index.py              # 正常构建
  python scripts/build_index.py --verbose    # 详细输出
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 输入
INPUT_FILE = PROJECT_ROOT / "data" / "procurements.json"

# 输出
AGGREGATIONS_FILE = PROJECT_ROOT / "data" / "aggregations.json"
SEARCH_INDEX_FILE = PROJECT_ROOT / "frontend" / "public" / "data" / "search-index.json"
FRONTEND_DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
FRONTEND_DATA_FILE = FRONTEND_DATA_DIR / "procurements.json"

logger = logging.getLogger(__name__)


# =============================================================================
# 数据加载
# =============================================================================
def load_data(path: Path) -> list[dict]:
    """加载采购项目数据"""
    if not path.exists():
        logger.error(f"数据文件不存在: {path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info(f"已加载 {len(data)} 条记录: {path}")
    return data


# =============================================================================
# 聚合统计
# =============================================================================
def build_aggregations(data: list[dict]) -> dict:
    """
    生成聚合统计数据，用于前端筛选面板渲染。

    输出结构:
    {
        "generated_at": "ISO timestamp",
        "total": 49,
        "regions": [{"name": "广州市", "count": 8}, ...],
        "categories": [{"name": "医学影像设备", "count": 7}, ...],
        "sources": [{"name": "gdgpo", "count": 12, "label": "广东省政府采购网"}, ...],
        "notice_types": [{"name": "采购公告", "count": 40}, ...],
        "date_range": {"earliest": "2026-05-10", "latest": "2026-06-05"},
        "budget_range": {"min": 0, "max": 1200, "avg": 256.5},
        "region_category_matrix": {"广州市": {"医学影像设备": 3, ...}, ...},
        "monthly_counts": {"2026-05": 12, "2026-06": 37}
    }
    """
    source_labels = {
        "gdgpo": "广东省政府采购网",
        "gdggzy": "广东省公共资源交易平台",
    }

    # 基础计数
    region_counter = Counter()
    category_counter = Counter()
    source_counter = Counter()
    notice_type_counter = Counter()

    # 交叉统计
    region_category_matrix: dict[str, Counter] = defaultdict(Counter)

    # 预算统计
    budgets: list[float] = []

    # 日期统计
    dates: list[str] = []
    monthly_counter = Counter()

    for item in data:
        region = item.get("region") or "未知"
        category = item.get("category") or "未分类"
        source = item.get("source") or "未知"
        notice_type = item.get("notice_type") or "未知"
        budget = item.get("budget")
        publish_date = item.get("publish_date") or ""

        region_counter[region] += 1
        category_counter[category] += 1
        source_counter[source] += 1
        notice_type_counter[notice_type] += 1
        region_category_matrix[region][category] += 1

        if budget is not None:
            budgets.append(float(budget))

        if publish_date:
            dates.append(publish_date)
            # 月度统计 (YYYY-MM)
            month_key = publish_date[:7]
            if len(month_key) == 7:
                monthly_counter[month_key] += 1

    # 排序并构建输出
    regions = [
        {"name": name, "count": count}
        for name, count in region_counter.most_common()
    ]

    categories = [
        {"name": name, "count": count}
        for name, count in category_counter.most_common()
    ]

    sources = [
        {"name": name, "count": count, "label": source_labels.get(name, name)}
        for name, count in source_counter.most_common()
    ]

    notice_types = [
        {"name": name, "count": count}
        for name, count in notice_type_counter.most_common()
    ]

    # 日期范围
    sorted_dates = sorted(dates) if dates else []
    date_range = {
        "earliest": sorted_dates[0] if sorted_dates else "",
        "latest": sorted_dates[-1] if sorted_dates else "",
    }

    # 预算范围
    budget_range = {}
    if budgets:
        budget_range = {
            "min": round(min(budgets), 2),
            "max": round(max(budgets), 2),
            "avg": round(sum(budgets) / len(budgets), 2),
            "median": round(sorted(budgets)[len(budgets) // 2], 2),
        }

    # 交叉矩阵 → 普通 dict
    matrix = {
        region: dict(cats.most_common())
        for region, cats in sorted(region_category_matrix.items())
    }

    # 月度统计 → 按时间排序
    monthly_counts = dict(sorted(monthly_counter.items()))

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(data),
        "regions": regions,
        "categories": categories,
        "sources": sources,
        "notice_types": notice_types,
        "date_range": date_range,
        "budget_range": budget_range,
        "region_category_matrix": matrix,
        "monthly_counts": monthly_counts,
    }

    return result


# =============================================================================
# FlexSearch 索引生成
# =============================================================================
def build_search_index(data: list[dict]) -> list[dict]:
    """
    生成 FlexSearch 兼容的文档数组。

    FlexSearch 在前端通过以下方式构建索引:
        const index = new FlexSearch.Document({
            document: {
                id: "id",
                index: ["project_name", "project_no", "hospital", "agency", "category"]
            }
        });
        documents.forEach(doc => index.add(doc));

    索引文档只包含搜索和列表展示所需字段（轻量），
    详情数据由前端从 procurements.json 中按 id 查找。
    """
    index_docs = []

    for item in data:
        doc = {
            # 唯一标识（用于关联详情数据）
            "id": item.get("project_id", ""),

            # === 搜索字段（FlexSearch 将索引这些字段） ===
            "project_name": item.get("project_name", ""),
            "project_no": item.get("project_no", ""),
            "hospital": item.get("hospital", ""),
            "agency": item.get("agency", ""),
            "category": item.get("category", ""),
            "raw_category": item.get("raw_category", ""),

            # === 筛选字段（用于前端 filter 逻辑，不需要全文索引） ===
            "region": item.get("region", ""),
            "budget": item.get("budget"),
            "publish_date": item.get("publish_date", ""),
            "source": item.get("source", ""),
            "notice_type": item.get("notice_type", ""),

            # === 展示字段 ===
            "url": item.get("url", ""),
            "content": (item.get("content") or "")[:300],  # 正文摘要（前300字）
        }
        index_docs.append(doc)

    logger.info(f"生成搜索索引: {len(index_docs)} 条文档")
    return index_docs


# =============================================================================
# 文件写入
# =============================================================================
def save_json(data: dict | list, path: Path, description: str) -> int:
    """保存 JSON 文件并返回文件大小"""
    path.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(data, ensure_ascii=False, indent=None, separators=(",", ":"))

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    size_bytes = path.stat().st_size
    size_kb = round(size_bytes / 1024, 1)
    logger.info(f"✅ {description}: {path} ({size_kb} KB)")
    return size_bytes


def save_json_pretty(data: dict | list, path: Path, description: str) -> int:
    """保存格式化的 JSON 文件（适合版本追踪）"""
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    size_bytes = path.stat().st_size
    size_kb = round(size_bytes / 1024, 1)
    logger.info(f"✅ {description}: {path} ({size_kb} KB)")
    return size_bytes


# =============================================================================
# 主函数
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="粤采雷达 - 搜索索引与聚合数据构建")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--input", type=str, default=None, help="自定义输入文件路径")
    args = parser.parse_args()

    # 日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    input_path = Path(args.input) if args.input else INPUT_FILE
    logger.info(f"{'=' * 50}")
    logger.info(f"粤采雷达 - 搜索索引构建")
    logger.info(f"{'=' * 50}")

    # 1. 加载数据
    data = load_data(input_path)
    if not data:
        logger.warning("数据为空，生成空索引")
        data = []

    # 2. 生成聚合统计
    logger.info("生成聚合统计数据...")
    aggregations = build_aggregations(data)
    agg_size = save_json_pretty(aggregations, AGGREGATIONS_FILE, "聚合统计")

    # 3. 生成 FlexSearch 索引
    logger.info("生成 FlexSearch 索引...")
    search_index = build_search_index(data)
    idx_size = save_json(search_index, SEARCH_INDEX_FILE, "搜索索引")

    # 4. 复制数据到前端目录
    logger.info("复制数据到前端目录...")
    FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_size = save_json(data, FRONTEND_DATA_FILE, "前端数据")

    # 同时复制聚合数据到前端
    save_json(aggregations, FRONTEND_DATA_DIR / "aggregations.json", "前端聚合数据")

    # 5. 输出构建摘要
    print(f"\n{'=' * 55}")
    print(f"  粤采雷达 - 索引构建完成")
    print(f"{'=' * 55}")
    print(f"  数据记录:     {len(data)} 条")
    print(f"  聚合统计:     {AGGREGATIONS_FILE.name} ({round(agg_size/1024, 1)} KB)")
    print(f"    - 地区:     {len(aggregations['regions'])} 个")
    print(f"    - 类目:     {len(aggregations['categories'])} 个")
    print(f"    - 日期范围: {aggregations['date_range'].get('earliest', 'N/A')}"
          f" ~ {aggregations['date_range'].get('latest', 'N/A')}")
    if aggregations.get("budget_range"):
        br = aggregations["budget_range"]
        print(f"    - 预算范围: {br.get('min', 0)} ~ {br.get('max', 0)} 万元")
    print(f"  搜索索引:     {SEARCH_INDEX_FILE.name} ({round(idx_size/1024, 1)} KB)")
    print(f"  前端数据:     {FRONTEND_DATA_FILE.name} ({round(data_size/1024, 1)} KB)")
    print(f"{'=' * 55}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
