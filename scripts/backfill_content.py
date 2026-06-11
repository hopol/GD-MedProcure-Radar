"""
粤采雷达 - 数据回填修复脚本
=============================
功能:
  1. 修复所有 GDGGZY URL 从 http 改为 https
  2. 回填 GDGPO 公告正文内容（调用详情 API）
  3. 重建搜索索引

用法:
  python scripts/backfill_content.py
"""
import json
import re
import sys
import time
import random
import logging
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scraper.config import GDGPO_CONFIG, GDGPO_HEADERS, HTTP_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")

DATA_FILE = PROJECT_ROOT / "data" / "procurements.json"


def load_data():
    """加载 procurements.json"""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    """保存 procurements.json"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"数据已保存: {DATA_FILE}")


def fix_gdggzy_urls(data):
    """修复所有 GDGGZY URL: http → https"""
    fixed = 0
    for item in data:
        url = item.get("url", "")
        if "ygp.gdzwfw.gov.cn" in url and url.startswith("http://"):
            item["url"] = url.replace("http://ygp.gdzwfw.gov.cn", "https://ygp.gdzwfw.gov.cn")
            fixed += 1
    logger.info(f"GDGGZY URL 修复: {fixed} 条 (http → https)")
    return fixed


def backfill_gdgpo_content(data):
    """回填 GDGPO 公告正文内容"""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    # 构建带重试的 session
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 筛选需要回填内容的 GDGPO 条目
    gdgpo_items = [
        item for item in data
        if item.get("source") == "gdgpo" and not item.get("content")
    ]

    if not gdgpo_items:
        logger.info("所有 GDGPO 条目已有正文内容，无需回填")
        return 0

    logger.info(f"需要回填正文的 GDGPO 条目: {len(gdgpo_items)} 条")

    success = 0
    for i, item in enumerate(gdgpo_items):
        url = item.get("url", "")
        nid = url.split("id=")[-1] if "id=" in url else ""
        if not nid:
            continue

        # 礼貌延迟
        delay = random.uniform(0.5, 1.2)
        time.sleep(delay)

        try:
            params = {
                "id": nid,
                "siteId": GDGPO_CONFIG["site_id"],
                "_t": int(time.time() * 1000),
            }
            headers = {
                **GDGPO_HEADERS,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            }
            resp = session.get(
                GDGPO_CONFIG["detail_api"],
                params=params,
                headers=headers,
                timeout=(45, 30),
            )
            resp.raise_for_status()
            result = resp.json()
            desc = result.get("data", {}).get("description", "")

            if desc:
                text = re.sub(r"<[^>]+>", "", desc)
                text = re.sub(r"\s+", " ", text).strip()
                item["content"] = text[:2000]
                success += 1

        except Exception as e:
            logger.debug(f"获取详情失败 (id={nid}): {e}")

        if (i + 1) % 5 == 0:
            logger.info(f"  进度: {i+1}/{len(gdgpo_items)} (成功 {success})")

    logger.info(f"GDGPO 正文回填完成: {success}/{len(gdgpo_items)} 条成功")
    return success


def main():
    logger.info("=" * 50)
    logger.info("粤采雷达 - 数据回填修复")
    logger.info("=" * 50)

    # 加载数据
    data = load_data()
    logger.info(f"加载数据: {len(data)} 条")

    # 1. 修复 GDGGZY URL
    url_fixed = fix_gdggzy_urls(data)

    # 2. 回填 GDGPO 正文内容
    content_filled = backfill_gdgpo_content(data)

    # 3. 统计
    has_content = sum(1 for item in data if item.get("content"))
    no_content = len(data) - has_content
    logger.info(f"\n统计: 共 {len(data)} 条, 有正文 {has_content} 条, 无正文 {no_content} 条")

    # 4. 保存
    save_data(data)

    logger.info("=" * 50)
    logger.info("回填修复完成！")
    logger.info(f"  URL 修复: {url_fixed} 条")
    logger.info(f"  正文回填: {content_filled} 条")
    logger.info("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
