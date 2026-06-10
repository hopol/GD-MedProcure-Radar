"""
粤采雷达 - 全局配置
"""
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 数据输出目录
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
OUTPUT_FILE = DATA_DIR / "procurements.json"

# 确保目录存在
for d in [RAW_DATA_DIR, PROCESSED_DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 数据源 1：广东省政府采购网 (gdgpo.czt.gd.gov.cn)
# =============================================================================
GDGPO_CONFIG = {
    "name": "广东省政府采购网",
    "base_url": "https://gdgpo.czt.gd.gov.cn",
    "list_api": "https://gdgpo.czt.gd.gov.cn/gpcms/rest/web/v2/info/selectInfoForIndex",
    "detail_api": "https://gdgpo.czt.gd.gov.cn/gpcms/rest/web/v2/info/getInfoById",
    "site_id": "cd64e06a-21a7-4620-aebc-0576bab7e07a",
    "channel": "fca71be5-fc0c-45db-96af-f513e9abda9d",
    "detail_url_template": "https://gdgpo.czt.gd.gov.cn/maincms-web/noticeGd?id={notice_id}",
    # 公告类型代码
    "notice_types": {
        "procurement_notice": "00101",     # 采购公告
        "bid_result": "00102",              # 中标（成交）结果公告
    },
    # 采购分类
    "purchase_nature": {
        "goods": "1",      # 货物（含医疗设备）
        "engineering": "2", # 工程
        "service": "3",     # 服务
    },
}

# =============================================================================
# 数据源 2：广东省公共资源交易平台 (ygp.gdzwfw.gov.cn)
# =============================================================================
GDGGZY_CONFIG = {
    "name": "广东省公共资源交易平台",
    "base_url": "http://ygp.gdzwfw.gov.cn",
    "search_api": "http://ygp.gdzwfw.gov.cn/ggzy-portal/search/v2/items",
    "site_code": 44,
    "trading_type_code": "D",  # 政府采购
    "detail_url_template": (
        "http://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/{trading_type_code}"
        "?noticeId={doc_id}&projectCode={project_code}"
        "&bizCode={trading_process}&siteCode={site_code}"
        "&publishDate={publish_date}&source={pub_service_plat}"
        "&titleDetails={notice_type_desc}&classify={trading_process}"
    ),
}


# =============================================================================
# 医疗设备关键词与品目过滤
# =============================================================================
# 标题关键词（用于搜索和过滤）
MEDICAL_KEYWORDS = [
    "医疗设备", "医疗器械", "医疗仪器", "医用设备",
    "CT", "MRI", "磁共振", "超声", "X光", "X线",
    "内窥镜", "呼吸机", "监护仪", "麻醉机", "手术床",
    "检验设备", "实验室设备", "影像设备", "诊断设备",
    "康复设备", "消毒设备", "输液泵", "注射泵",
    "心电图", "脑电图", "彩超", "B超",
    "医用", "医用耗材", "高值耗材",
]

# 品目分类映射
CATEGORY_MAPPING = {
    "医学影像设备": ["CT", "MRI", "磁共振", "X光", "X线", "DR", "超声", "彩超", "B超", "影像"],
    "检验设备": ["检验", "实验室", "生化", "免疫", "血液分析", "PCR"],
    "手术设备": ["手术", "麻醉", "手术床", "无影灯", "电刀"],
    "监护设备": ["监护", "心电", "脑电", "血氧"],
    "呼吸设备": ["呼吸", "通气", "氧疗"],
    "康复设备": ["康复", "理疗", "物理治疗"],
    "消毒设备": ["消毒", "灭菌"],
    "其他医疗设备": [],
}


# =============================================================================
# HTTP 请求配置（已优化 — 兼顾效率与稳定性）
# =============================================================================
HTTP_CONFIG = {
    "connect_timeout": 20,       # 连接超时（秒）— 从 60s 降至 20s，快速失败
    "read_timeout": 30,          # 读取超时（秒）— 从 120s 降至 30s
    "timeout": (20, 30),         # (connect, read) 元组，供 requests 库使用
    "max_retries": 3,            # 最大重试次数 — 从 5 降至 3，减少无效等待
    "retry_delay": 3,            # 重试间隔基数（秒）— 从 5 降至 3
    "request_delay": (0.8, 1.5), # 列表页请求间隔（秒）— 从 (2,5) 大幅降低
    "detail_delay": (0.3, 0.8),  # 详情 API 专用短延迟（独立接口压力小）
    "page_size": 50,             # 每页条数 — 从 20 提升至 50，减少翻页次数
    "max_pages": 50,             # 单次采集最大页数（防止无限循环）
    "fetch_content": True,        # 是否采集公告正文内容（调用详情 API）
}

# 请求头池（模拟不同浏览器）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.2420.81",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

# 通用请求头
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

# GDGPO 专用请求头
GDGPO_HEADERS = {
    **DEFAULT_HEADERS,
    "Origin": "https://gdgpo.czt.gd.gov.cn",
    "Referer": "https://gdgpo.czt.gd.gov.cn/maincms-web/noticeInformationGd",
}

# GDGGZY 专用请求头
GDGGZY_HEADERS = {
    **DEFAULT_HEADERS,
    "Content-Type": "application/json",
    "Origin": "http://ygp.gdzwfw.gov.cn",
    "Referer": "http://ygp.gdzwfw.gov.cn/",
}


# =============================================================================
# 日志配置
# =============================================================================
LOG_CONFIG = {
    "level": os.environ.get("LOG_LEVEL", "INFO"),
    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    "datefmt": "%Y-%m-%d %H:%M:%S",
}
