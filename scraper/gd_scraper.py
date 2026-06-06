"""
粤采雷达 - 核心爬虫引擎
======================
数据源 1：广东省政府采购网 (gdgpo.czt.gd.gov.cn) — REST API 直调
数据源 2：广东省公共资源交易平台 (ygp.gdzwfw.gov.cn) — REST API 直调
备选方案：Playwright 浏览器渲染（当 API 结构变更时启用）
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper.config import (
    CATEGORY_MAPPING,
    DEFAULT_HEADERS,
    GDGPO_CONFIG,
    GDGPO_HEADERS,
    GDGGZY_CONFIG,
    GDGGZY_HEADERS,
    HTTP_CONFIG,
    MEDICAL_KEYWORDS,
    USER_AGENTS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 数据模型
# =============================================================================
@dataclass
class ProcurementItem:
    """采购项目数据模型"""

    project_id: str = ""            # 内部唯一 ID（基于 URL 或公告 ID 的哈希）
    project_no: str = ""            # 项目编号（采购编号）
    project_name: str = ""          # 项目名称
    hospital: str = ""              # 采购人/医院
    region: str = ""                # 所属地区（地级市）
    category: str = ""              # 标准化品目分类
    budget: Optional[float] = None  # 预算金额（万元）
    publish_date: str = ""          # 发布时间 (YYYY-MM-DD)
    url: str = ""                   # 公告链接
    source: str = ""                # 数据来源标识
    raw_category: str = ""          # 原始品目文本
    agency: str = ""                # 招标代理机构
    notice_type: str = ""           # 公告类型
    crawl_time: str = ""            # 采集时间
    content: str = ""               # 公告正文内容（纯文本摘要）

    def to_dict(self) -> dict:
        return asdict(self)


# =============================================================================
# 基础爬虫类
# =============================================================================
class BaseScraper(ABC):
    """爬虫基类：封装 HTTP 请求、重试、限速、日志"""

    def __init__(self, name: str):
        self.name = name
        self.session = self._build_session()
        self._request_count = 0

    def _build_session(self) -> requests.Session:
        """构建带自动重试的 requests Session（针对海外服务器访问国内网站优化）"""
        session = requests.Session()
        retry = Retry(
            total=HTTP_CONFIG["max_retries"],
            backoff_factor=HTTP_CONFIG["retry_delay"],
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
            # 连接错误也重试（包括 ConnectTimeout）
            connect=HTTP_CONFIG["max_retries"],
            read=HTTP_CONFIG["max_retries"],
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=5, pool_maxsize=5)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_headers(self, extra: dict | None = None) -> dict:
        """获取请求头，随机选择 User-Agent"""
        headers = {
            **(extra or {}),
            "User-Agent": random.choice(USER_AGENTS),
        }
        return headers

    def _polite_delay(self):
        """礼貌延迟，避免对目标服务器造成压力"""
        lo, hi = HTTP_CONFIG["request_delay"]
        delay = random.uniform(lo, hi)
        time.sleep(delay)

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None) -> requests.Response:
        """发起 GET 请求（带限速和日志）"""
        self._polite_delay()
        self._request_count += 1
        merged = self._get_headers(headers)
        logger.debug(f"[{self.name}] GET {url} params={params}")
        resp = self.session.get(url, params=params, headers=merged, timeout=HTTP_CONFIG["timeout"])
        resp.raise_for_status()
        return resp

    def _post(self, url: str, json_body: dict | None = None, headers: dict | None = None) -> requests.Response:
        """发起 POST 请求（带限速和日志）"""
        self._polite_delay()
        self._request_count += 1
        merged = self._get_headers(headers)
        logger.debug(f"[{self.name}] POST {url} body={json_body}")
        resp = self.session.post(url, json=json_body, headers=merged, timeout=HTTP_CONFIG["timeout"])
        resp.raise_for_status()
        return resp

    @staticmethod
    def make_project_id(source: str, raw_id: str) -> str:
        """生成唯一项目 ID"""
        raw = f"{source}:{raw_id}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    @staticmethod
    def classify_category(text: str) -> str:
        """根据标题/品目文本推断标准化品目分类"""
        if not text:
            return "其他医疗设备"
        text_lower = text.lower()
        for category, keywords in CATEGORY_MAPPING.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    return category
        return "其他医疗设备"

    @staticmethod
    def is_medical_related(title: str, catalogue_names: list[str] | None = None) -> bool:
        """判断采购项目是否与医疗设备相关"""
        combined = title or ""
        if catalogue_names:
            combined += " " + " ".join(catalogue_names)
        combined_lower = combined.lower()
        return any(kw.lower() in combined_lower for kw in MEDICAL_KEYWORDS)

    @abstractmethod
    def crawl(self, start_date: str | None = None, end_date: str | None = None,
              max_pages: int | None = None) -> list[ProcurementItem]:
        """
        执行采集，返回采购项目列表。
        :param start_date: 开始日期 YYYY-MM-DD（默认 30 天前）
        :param end_date: 结束日期 YYYY-MM-DD（默认今天）
        :param max_pages: 最大页数限制
        """
        ...

    def get_stats(self) -> dict:
        return {"name": self.name, "request_count": self._request_count}


# =============================================================================
# 数据源 1：广东省政府采购网
# =============================================================================
class GDGPOScraper(BaseScraper):
    """
    广东省政府采购网爬虫
    目标: https://gdgpo.czt.gd.gov.cn
    方式: 直接调用 REST API (selectInfoForIndex / getInfoById)
    """

    def __init__(self):
        super().__init__("广东省政府采购网")

    def crawl(self, start_date: str | None = None, end_date: str | None = None,
              max_pages: int | None = None) -> list[ProcurementItem]:
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if max_pages is None:
            max_pages = HTTP_CONFIG["max_pages"]

        items: list[ProcurementItem] = []
        page = 1
        total = None

        logger.info(f"[{self.name}] 开始采集: {start_date} ~ {end_date}, 最大 {max_pages} 页")

        while page <= max_pages:
            logger.info(f"[{self.name}] 采集第 {page} 页... (已获取 {len(items)} 条)")

            try:
                data = self._fetch_list_page(page, start_date, end_date)
            except Exception as e:
                if page == 1:
                    # 第 1 页失败时额外等待后重试一次（海外服务器访问国内网站可能需要更长时间）
                    logger.warning(f"[{self.name}] 第 1 页首次失败，等待 30 秒后重试: {e}")
                    time.sleep(30)
                    try:
                        data = self._fetch_list_page(page, start_date, end_date)
                    except Exception as e2:
                        logger.error(f"[{self.name}] 第 1 页重试仍然失败: {e2}")
                        break
                else:
                    logger.error(f"[{self.name}] 第 {page} 页请求失败: {e}")
                    break

            # 解析分页信息
            if total is None:
                total = data.get("total", 0)
                logger.info(f"[{self.name}] 共找到 {total} 条记录")

            records = data.get("rows", [])
            if not records:
                logger.info(f"[{self.name}] 第 {page} 页无数据，采集结束")
                break

            for record in records:
                item = self._parse_record(record)
                if item:
                    items.append(item)

            # 检查是否还有下一页
            fetched_so_far = page * HTTP_CONFIG["page_size"]
            if total and fetched_so_far >= total:
                break

            page += 1

        logger.info(f"[{self.name}] 列表采集完成: 共 {len(items)} 条医疗设备相关记录")

        # 采集公告正文内容
        if items and HTTP_CONFIG.get("fetch_content", True):
            logger.info(f"[{self.name}] 开始采集公告正文内容 ({len(items)} 条)...")
            success = 0
            for i, item in enumerate(items):
                # 从 URL 中提取 notice_id
                url = item.url or ""
                nid = url.split("id=")[-1] if "id=" in url else ""
                if not nid:
                    continue
                try:
                    detail = self.fetch_detail(nid)
                    desc = detail.get("description", "")
                    if desc:
                        # 去除 HTML 标签，保留纯文本
                        import re
                        text = re.sub(r"<[^>]+>", "", desc)
                        text = re.sub(r"\s+", " ", text).strip()
                        # 截取前 2000 字作为摘要
                        item.content = text[:2000]
                        success += 1
                    self._polite_delay()
                except Exception as e:
                    logger.debug(f"[{self.name}] 获取详情失败 (noticeId={nid}): {e}")
                if (i + 1) % 5 == 0:
                    logger.info(f"[{self.name}] 详情进度: {i+1}/{len(items)} (成功 {success})")
            logger.info(f"[{self.name}] 详情采集完成: {success}/{len(items)} 条成功")

        return items

    def _fetch_list_page(self, page: int, start_date: str, end_date: str) -> dict:
        """获取列表页 API 数据"""
        params = {
            "siteId": GDGPO_CONFIG["site_id"],
            "channel": GDGPO_CONFIG["channel"],
            "currPage": page,
            "pageSize": HTTP_CONFIG["page_size"],
            "noticeType": GDGPO_CONFIG["notice_types"]["procurement_notice"],
            "purchaseNature": GDGPO_CONFIG["purchase_nature"]["goods"],
            "operationStartTime": f"{start_date} 00:00:00",
            "operationEndTime": f"{end_date} 23:59:59",
            "title": "",
            "openTenderCode": "",
            "purchaser": "",
            "agency": "",
            "regionCode": "",
            "cityOrArea": "",
            "verifyCode": "",
            "subChannel": "false",
            "_t": int(time.time() * 1000),
        }
        resp = self._get(GDGPO_CONFIG["list_api"], params=params, headers=GDGPO_HEADERS)
        result = resp.json()

        if result.get("code") not in (200, "200"):
            raise ValueError(f"API 返回异常: code={result.get('code')}, msg={result.get('msg')}")

        return result.get("data", {})

    def _parse_record(self, record: dict) -> ProcurementItem | None:
        """解析单条 API 记录为 ProcurementItem"""
        try:
            title = record.get("title", "").strip()
            # catalogueNameList 可能是字符串（逗号分隔）或列表
            catalogue_raw = record.get("catalogueNameList", "")
            if isinstance(catalogue_raw, list):
                catalogue_list = [s.strip() for s in catalogue_raw if s]
            elif isinstance(catalogue_raw, str) and catalogue_raw:
                catalogue_list = [s.strip() for s in catalogue_raw.split(",") if s.strip()]
            else:
                catalogue_list = []
            catalogue_text = ", ".join(catalogue_list) if catalogue_list else ""

            # 过滤：只保留医疗设备相关
            if not self.is_medical_related(title, catalogue_list):
                return None

            notice_id = str(record.get("noticeId", ""))
            notice_time = record.get("noticeTime", "")
            region_name = record.get("regionName", "").strip()
            purchaser = record.get("purchaser", "").strip()
            agency = record.get("agency", "").strip()
            open_tender_code = record.get("openTenderCode", "").strip()
            budget_raw = record.get("budget")

            # 预算金额：API 返回元为单位的字符串，转换为万元
            budget = None
            if budget_raw is not None:
                try:
                    budget_val = float(str(budget_raw).replace(",", "").strip())
                    # API 返回的是元，转换为万元
                    budget = round(budget_val / 10000, 4)
                except (ValueError, TypeError):
                    budget = None

            # 日期格式化
            publish_date = ""
            if notice_time:
                try:
                    if "T" in notice_time or len(notice_time) > 10:
                        publish_date = notice_time[:10]
                    else:
                        publish_date = notice_time
                except Exception:
                    publish_date = notice_time[:10] if len(notice_time) >= 10 else notice_time

            # 品目分类推断
            combined_text = f"{title} {catalogue_text}"
            category = self.classify_category(combined_text)

            # 详情 URL
            url = GDGPO_CONFIG["detail_url_template"].format(notice_id=notice_id)

            return ProcurementItem(
                project_id=self.make_project_id("gdgpo", notice_id),
                project_no=open_tender_code,
                project_name=title,
                hospital=purchaser,
                region=region_name,
                category=category,
                budget=budget,
                publish_date=publish_date,
                url=url,
                source="gdgpo",
                raw_category=catalogue_text,
                agency=agency,
                notice_type="采购公告",
                crawl_time=datetime.now().isoformat(timespec="seconds"),
            )

        except Exception as e:
            logger.warning(f"[{self.name}] 解析记录失败: {e}, record={record.get('noticeId', '?')}")
            return None

    def fetch_detail(self, notice_id: str) -> dict:
        """获取公告详情（可选，用于获取完整正文）"""
        params = {
            "id": notice_id,
            "siteId": GDGPO_CONFIG["site_id"],
            "_t": int(time.time() * 1000),
        }
        resp = self._get(GDGPO_CONFIG["detail_api"], params=params, headers=GDGPO_HEADERS)
        result = resp.json()
        return result.get("data", {})


# =============================================================================
# 数据源 2：广东省公共资源交易平台
# =============================================================================
class GDGGZYScraper(BaseScraper):
    """
    广东省公共资源交易平台爬虫
    目标: http://ygp.gdzwfw.gov.cn
    方式: 调用 search/v2/items POST API
    """

    def __init__(self):
        super().__init__("广东省公共资源交易平台")

    def crawl(self, start_date: str | None = None, end_date: str | None = None,
              max_pages: int | None = None) -> list[ProcurementItem]:
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if max_pages is None:
            max_pages = HTTP_CONFIG["max_pages"]

        items: list[ProcurementItem] = []
        total = None

        logger.info(f"[{self.name}] 开始采集: {start_date} ~ {end_date}, 最大 {max_pages} 页")

        # 使用多个医疗关键词进行搜索，合并结果
        search_keywords = ["医疗设备", "医疗器械", "医用设备", "医疗仪器"]

        for keyword in search_keywords:
            logger.info(f"[{self.name}] 搜索关键词: '{keyword}'")
            page = 1
            kw_total = None

            while page <= max_pages:
                logger.info(f"[{self.name}] 关键词 '{keyword}' 第 {page} 页... (已获取 {len(items)} 条)")

                try:
                    data = self._fetch_list_page(page, start_date, end_date, keyword)
                except requests.exceptions.HTTPError as e:
                    if e.response is not None and e.response.status_code == 429:
                        logger.warning(f"[{self.name}] 触发频率限制 (429)，等待 30 秒后重试...")
                        time.sleep(30)
                        try:
                            data = self._fetch_list_page(page, start_date, end_date, keyword)
                        except Exception as retry_e:
                            logger.error(f"[{self.name}] 重试失败: {retry_e}")
                            break
                    else:
                        logger.error(f"[{self.name}] 第 {page} 页请求失败: {e}")
                        break
                except Exception as e:
                    if page == 1:
                        logger.warning(f"[{self.name}] 关键词 '{keyword}' 第 1 页首次失败，等待 30 秒后重试: {e}")
                        time.sleep(30)
                        try:
                            data = self._fetch_list_page(page, start_date, end_date, keyword)
                        except Exception as e2:
                            logger.error(f"[{self.name}] 重试仍然失败: {e2}")
                            break
                    else:
                        logger.error(f"[{self.name}] 第 {page} 页请求失败: {e}")
                        break

                if kw_total is None:
                    kw_total = int(data.get("total", 0))
                    logger.info(f"[{self.name}] 关键词 '{keyword}' 共 {kw_total} 条")

                records = data.get("pageData", [])
                if not records:
                    break

                for record in records:
                    item = self._parse_record(record)
                    if item:
                        items.append(item)

                fetched_so_far = page * HTTP_CONFIG["page_size"]
                if kw_total and fetched_so_far >= kw_total:
                    break

                page += 1

        logger.info(f"[{self.name}] 采集完成: 共 {len(items)} 条医疗设备相关记录")
        return items

    def _fetch_list_page(self, page: int, start_date: str, end_date: str,
                         keyword: str = "医疗设备") -> dict:
        """获取搜索列表 API 数据"""
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")

        body = {
            "siteCode": GDGGZY_CONFIG["site_code"],
            "pageNo": page,
            "pageSize": HTTP_CONFIG["page_size"],
            "tradingTypeCode": GDGGZY_CONFIG["trading_type_code"],
            "startTime": start_fmt,
            "endTime": end_fmt,
            "keyword": keyword,
            "noticeType": "",
        }

        resp = self._post(GDGGZY_CONFIG["search_api"], json_body=body, headers=GDGGZY_HEADERS)
        result = resp.json()

        # GDGGZY API 使用 errcode=0 表示成功
        if result.get("errcode", -1) != 0 and result.get("code") not in (200, "200"):
            raise ValueError(f"API 返回异常: errcode={result.get('errcode')}, errmsg={result.get('errmsg')}")

        return result.get("data", {})

    def _parse_record(self, record: dict) -> ProcurementItem | None:
        """解析单条搜索记录为 ProcurementItem"""
        try:
            title = (record.get("noticeTitle") or "").strip()
            # 去掉 HTML 高亮标签
            import re
            title = re.sub(r"<[^>]+>", "", title)

            if not title:
                return None

            project_owner = (record.get("projectOwner") or "").strip()
            project_code = (record.get("projectCode") or "").strip()
            region_name = (record.get("regionName") or "").strip()
            dataset_name = (record.get("datasetName") or "").strip()
            pub_plat = (record.get("pubServicePlat") or "").strip()
            doc_id = record.get("docId") or ""
            publish_date_raw = record.get("publishDate") or ""
            trading_process = str(record.get("tradingProcess") or "")
            site_code = str(record.get("siteCode") or "")
            notice_type_desc = (record.get("noticeSecondTypeDesc") or "").strip()

            # 过滤：只保留医疗设备相关
            if not self.is_medical_related(title):
                return None

            # 日期格式化 (YYYYMMDDHHmmss → YYYY-MM-DD)
            publish_date = ""
            if publish_date_raw and len(publish_date_raw) >= 8:
                publish_date = f"{publish_date_raw[:4]}-{publish_date_raw[4:6]}-{publish_date_raw[6:8]}"

            # 品目分类推断
            category = self.classify_category(title)

            # 详情 URL
            url = GDGGZY_CONFIG["detail_url_template"].format(
                trading_type_code=GDGGZY_CONFIG["trading_type_code"],
                doc_id=quote(str(doc_id)),
                project_code=quote(project_code),
                trading_process=quote(str(trading_process)),
                site_code=quote(str(site_code)),
                publish_date=quote(publish_date_raw),
                pub_service_plat=quote(pub_plat),
                notice_type_desc=quote(notice_type_desc),
            )

            return ProcurementItem(
                project_id=self.make_project_id("gdggzy", str(doc_id)),
                project_no=project_code,
                project_name=title,
                hospital=project_owner,
                region=region_name,
                category=category,
                publish_date=publish_date,
                url=url,
                source="gdggzy",
                raw_category=dataset_name,
                agency="",
                notice_type=notice_type_desc or "采购公告",
                crawl_time=datetime.now().isoformat(timespec="seconds"),
            )

        except Exception as e:
            logger.warning(f"[{self.name}] 解析记录失败: {e}, docId={record.get('docId', '?')}")
            return None


# =============================================================================
# Playwright 备选爬虫（当 API 结构变更时使用）
# =============================================================================
class PlaywrightFallbackScraper:
    """
    Playwright 浏览器渲染备选方案。
    当主 API 发生结构性变更（字段缺失、接口失效）时手动启用。

    使用方式:
        scraper = PlaywrightFallbackScraper()
        items = await scraper.crawl_async()

    注意: 需要在环境中安装 Playwright:
        pip install playwright
        playwright install chromium
    """

    def __init__(self):
        self.name = "Playwright 备选爬虫"

    def crawl(self, start_date: str | None = None, end_date: str | None = None,
              max_pages: int | None = None) -> list[ProcurementItem]:
        """同步入口（内部运行异步事件循环）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(
                        asyncio.run,
                        self.crawl_async(start_date, end_date, max_pages)
                    ).result()
            else:
                return loop.run_until_complete(self.crawl_async(start_date, end_date, max_pages))
        except RuntimeError:
            return asyncio.run(self.crawl_async(start_date, end_date, max_pages))

    async def crawl_async(self, start_date: str | None = None, end_date: str | None = None,
                          max_pages: int | None = None) -> list[ProcurementItem]:
        """
        使用 Playwright 渲染广东省政府采购网页面，从 DOM 中提取采购公告列表。
        仅在 API 方式失效时使用。
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright 未安装，请执行: pip install playwright && playwright install chromium")
            return []

        items: list[ProcurementItem] = []
        max_pages = max_pages or 5

        logger.info(f"[{self.name}] 启动 Playwright 浏览器采集...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            # 拦截 API 响应，直接从网络请求中提取数据（比 DOM 解析更可靠）
            api_data: list[dict] = []

            async def handle_response(response):
                if "selectInfoForIndex" in response.url:
                    try:
                        body = await response.json()
                        if "data" in body and "list" in body["data"]:
                            api_data.extend(body["data"]["list"])
                    except Exception:
                        pass

            page.on("response", handle_response)

            list_url = "https://gdgpo.czt.gd.gov.cn/maincms-web/noticeInformationGd"

            for page_num in range(1, max_pages + 1):
                logger.info(f"[{self.name}] 加载第 {page_num} 页...")
                try:
                    await page.goto(list_url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(3000)

                    if page_num > 1:
                        # 尝试点击下一页按钮
                        next_btn = page.locator("button.btn-next:not([disabled])")
                        if await next_btn.count() > 0:
                            await next_btn.click()
                            await page.wait_for_timeout(3000)
                        else:
                            logger.info(f"[{self.name}] 无下一页按钮，采集结束")
                            break

                except Exception as e:
                    logger.error(f"[{self.name}] 页面加载失败: {e}")
                    break

            await browser.close()

        # 使用 GDGPOScraper 的解析逻辑处理拦截到的 API 数据
        gdgpo = GDGPOScraper()
        for record in api_data:
            item = gdgpo._parse_record(record)
            if item:
                items.append(item)

        logger.info(f"[{self.name}] 采集完成: {len(items)} 条记录 (通过 Playwright 拦截 API)")
        return items


# =============================================================================
# 工厂函数
# =============================================================================
def create_all_scrapers() -> list[BaseScraper]:
    """创建所有爬虫实例"""
    return [
        GDGPOScraper(),
        GDGGZYScraper(),
    ]
