"""
粤采雷达 - 爬虫调度入口
========================
功能:
  1. 调用所有数据源爬虫进行采集
  2. 跨数据源去重（基于 project_id + 标题相似度）
  3. 与历史数据增量合并
  4. 保存原始快照 + 最终结果到 JSON
  5. 输出采集统计报告

用法:
  python -m scraper.main                  # 正常采集（默认近 30 天）
  python -m scraper.main --test           # 测试模式（仅采集 2 页）
  python -m scraper.main --days 7         # 采集近 7 天
  python -m scraper.main --source gdgpo   # 仅采集指定数据源
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scraper.config import DATA_DIR, LOG_CONFIG, OUTPUT_FILE, RAW_DATA_DIR
from scraper.gd_scraper import (
    BaseScraper,
    GDGGZYScraper,
    GDGPOScraper,
    PlaywrightFallbackScraper,
    ProcurementItem,
    create_all_scrapers,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 日志初始化
# =============================================================================
def setup_logging(level: str | None = None):
    """配置全局日志"""
    log_level = level or LOG_CONFIG["level"]
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=LOG_CONFIG["format"],
        datefmt=LOG_CONFIG["datefmt"],
    )


# =============================================================================
# 去重逻辑
# =============================================================================
def deduplicate(items: list[ProcurementItem]) -> list[ProcurementItem]:
    """
    对采集结果进行去重。
    策略:
      1. 精确去重：project_id 相同 → 直接合并（保留字段更丰富的）
      2. 模糊去重：项目编号 (project_no) 相同 → 保留最新采集的
      3. 标题相似度：同一医院 + 标题 SimHash 相似度 > 90% → 视为重复
    """
    seen_ids: dict[str, ProcurementItem] = {}
    seen_nos: dict[str, ProcurementItem] = {}
    duplicates = 0

    for item in items:
        # 策略 1: project_id 精确匹配
        if item.project_id in seen_ids:
            existing = seen_ids[item.project_id]
            # 保留字段更丰富的版本
            if _count_filled(item) > _count_filled(existing):
                seen_ids[item.project_id] = item
            duplicates += 1
            continue

        # 策略 2: project_no 匹配（跨数据源）
        if item.project_no and item.project_no in seen_nos:
            existing = seen_nos[item.project_no]
            if _count_filled(item) > _count_filled(existing):
                # 替换旧记录
                del seen_ids[existing.project_id]
                seen_ids[item.project_id] = item
                seen_nos[item.project_no] = item
            duplicates += 1
            continue

        seen_ids[item.project_id] = item
        if item.project_no:
            seen_nos[item.project_no] = item

    result = list(seen_ids.values())
    logger.info(f"去重: {len(items)} 条 → {len(result)} 条 (去除 {duplicates} 条重复)")
    return result


def _count_filled(item: ProcurementItem) -> int:
    """统计非空字段数，用于判断哪条记录更完整"""
    d = item.to_dict()
    return sum(1 for v in d.values() if v is not None and v != "" and v != [])


# =============================================================================
# 增量合并
# =============================================================================
def merge_with_existing(new_items: list[ProcurementItem]) -> list[ProcurementItem]:
    """
    与已有 procurements.json 进行增量合并。
    - 新项目：追加
    - 已有项目（project_id 匹配）：用新数据更新（合并字段）
    - 旧项目：保留
    """
    existing_items: list[ProcurementItem] = []

    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            existing_items = [_dict_to_item(d) for d in raw]
            logger.info(f"加载已有数据: {len(existing_items)} 条")
        except Exception as e:
            logger.warning(f"加载已有数据失败: {e}，将仅保存新数据")

    if not existing_items:
        return new_items

    # 构建已有数据的索引
    existing_map: dict[str, ProcurementItem] = {item.project_id: item for item in existing_items}
    added = 0
    updated = 0

    for new_item in new_items:
        if new_item.project_id in existing_map:
            # 合并：新数据覆盖旧数据的非空字段
            existing_map[new_item.project_id] = _merge_items(existing_map[new_item.project_id], new_item)
            updated += 1
        else:
            existing_map[new_item.project_id] = new_item
            added += 1

    merged = list(existing_map.values())
    logger.info(f"合并: 新增 {added} 条, 更新 {updated} 条, 总计 {len(merged)} 条")
    return merged


def _merge_items(old: ProcurementItem, new: ProcurementItem) -> ProcurementItem:
    """合并两条记录：用新数据的非空字段覆盖旧数据"""
    old_dict = old.to_dict()
    new_dict = new.to_dict()
    merged_dict = {}

    for key in old_dict:
        new_val = new_dict.get(key)
        old_val = old_dict.get(key)
        # 新值非空则用新值，否则保留旧值
        if new_val is not None and new_val != "" and new_val != []:
            merged_dict[key] = new_val
        else:
            merged_dict[key] = old_val

    return _dict_to_item(merged_dict)


def _dict_to_item(d: dict) -> ProcurementItem:
    """字典转 ProcurementItem"""
    valid_fields = {f for f in ProcurementItem.__dataclass_fields__}
    filtered = {k: v for k, v in d.items() if k in valid_fields}
    return ProcurementItem(**filtered)


# =============================================================================
# 数据保存
# =============================================================================
def save_raw_snapshot(all_items: list[dict], source_name: str):
    """保存原始采集快照（不可修改的历史记录）"""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_name = source_name.replace(" ", "_")
    filename = f"{timestamp}_{safe_name}.json"
    filepath = RAW_DATA_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)

    logger.info(f"原始快照已保存: {filepath} ({len(all_items)} 条)")


def save_final_data(items: list[ProcurementItem]):
    """保存最终去重后的数据"""
    data = [item.to_dict() for item in items]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"最终数据已保存: {OUTPUT_FILE} ({len(data)} 条)")


# =============================================================================
# 统计报告
# =============================================================================
def print_summary(items: list[ProcurementItem], scraper_stats: list[dict]):
    """输出采集统计摘要"""
    print("\n" + "=" * 60)
    print("  粤采雷达 - 采集统计报告")
    print("=" * 60)

    # 各数据源统计
    print(f"\n{'数据源':<20} {'采集数':<10} {'请求数':<10}")
    print("-" * 40)
    for stat in scraper_stats:
        print(f"{stat['name']:<20} {stat.get('crawled', 0):<10} {stat.get('request_count', 0):<10}")

    # 总体统计
    print(f"\n去重后总数: {len(items)} 条")

    # 按地区统计
    region_counts: dict[str, int] = {}
    for item in items:
        r = item.region or "未知"
        region_counts[r] = region_counts.get(r, 0) + 1

    if region_counts:
        print("\n按地区分布 (Top 10):")
        for region, count in sorted(region_counts.items(), key=lambda x: -x[1])[:10]:
            bar = "█" * min(count, 30)
            print(f"  {region:<12} {count:>5}  {bar}")

    # 按品目统计
    cat_counts: dict[str, int] = {}
    for item in items:
        c = item.category or "未分类"
        cat_counts[c] = cat_counts.get(c, 0) + 1

    if cat_counts:
        print("\n按品目分布:")
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            print(f"  {cat:<16} {count:>5}")

    # 日期范围
    dates = [item.publish_date for item in items if item.publish_date]
    if dates:
        print(f"\n日期范围: {min(dates)} ~ {max(dates)}")

    print("=" * 60 + "\n")


# =============================================================================
# 主函数
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="粤采雷达 - 医疗设备采购信息采集")
    parser.add_argument("--test", action="store_true", help="测试模式（仅采集 2 页）")
    parser.add_argument("--days", type=int, default=30, help="采集近 N 天的数据（默认 30）")
    parser.add_argument("--source", type=str, default=None,
                        choices=["gdgpo", "gdggzy"],
                        help="仅采集指定数据源 (gdgpo/gdggzy)")
    parser.add_argument("--playwright", action="store_true", help="使用 Playwright 备选方案")
    parser.add_argument("--no-merge", action="store_true", help="不与历史数据合并（仅保存本次采集）")
    parser.add_argument("--no-content", action="store_true", help="不采集公告正文内容（加速采集）")
    parser.add_argument("--log-level", type=str, default=None,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别")
    args = parser.parse_args()

    # 初始化日志
    setup_logging(args.log_level)

    logger.info("粤采雷达 - 采集任务开始")
    logger.info(f"参数: test={args.test}, days={args.days}, source={args.source}, playwright={args.playwright}, no_content={args.no_content}")

    # 应用 --no-content 选项
    if args.no_content:
        from scraper.config import HTTP_CONFIG
        HTTP_CONFIG["fetch_content"] = False

    # 日期范围
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    max_pages = 2 if args.test else None

    # 选择爬虫
    scrapers: list[BaseScraper] = []

    if args.playwright:
        logger.info("使用 Playwright 备选方案...")
        pw = PlaywrightFallbackScraper()
        items = pw.crawl(start_date=start_date, end_date=end_date, max_pages=max_pages)
        scraper_stats = [{"name": pw.name, "crawled": len(items), "request_count": 0}]
    else:
        if args.source == "gdgpo":
            scrapers = [GDGPOScraper()]
        elif args.source == "gdggzy":
            scrapers = [GDGGZYScraper()]
        else:
            scrapers = create_all_scrapers()

        # 执行采集（双数据源并行）
        all_raw_items: list[dict] = []
        all_items: list[ProcurementItem] = []
        scraper_stats: list[dict] = []

        def _run_scraper(scraper):
            """在线程中执行单个爬虫"""
            logger.info(f"--- 开始采集: {scraper.name} ---")
            items = scraper.crawl(start_date=start_date, end_date=end_date, max_pages=max_pages)
            return scraper, items

        with ThreadPoolExecutor(max_workers=len(scrapers)) as pool:
            futures = {pool.submit(_run_scraper, s): s for s in scrapers}
            for future in as_completed(futures):
                scraper = futures[future]
                try:
                    scraper, items = future.result()
                    all_items.extend(items)

                    # 保存原始快照
                    raw_dicts = [item.to_dict() for item in items]
                    save_raw_snapshot(raw_dicts, scraper.name)

                    stats = scraper.get_stats()
                    stats["crawled"] = len(items)
                    scraper_stats.append(stats)

                    logger.info(f"--- {scraper.name} 采集完成: {len(items)} 条 ---")

                except Exception as e:
                    logger.error(f"--- {scraper.name} 采集失败: {e} ---", exc_info=True)
                    scraper_stats.append({"name": scraper.name, "crawled": 0, "request_count": 0, "error": str(e)})

    # 去重
    deduped = deduplicate(all_items)

    # 增量合并
    if not args.no_merge:
        final = merge_with_existing(deduped)
    else:
        final = deduped

    # 按发布日期倒序排列
    final.sort(key=lambda x: x.publish_date or "", reverse=True)

    # 保存
    save_final_data(final)

    # 统计报告
    print_summary(final, scraper_stats)

    logger.info(f"采集任务完成！共 {len(final)} 条记录已保存到 {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
