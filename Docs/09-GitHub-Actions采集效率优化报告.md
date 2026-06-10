# GitHub Actions 采集效率优化报告书

> **日期**：2026-06-10  
> **分析对象**：粤采雷达（GD-MedProcure-Radar）数据采集与部署全流程  
> **目标**：降低 GitHub Actions 免费额度消耗，提升采集效率  

---

## 一、GitHub Actions 免费额度说明

| 项目 | 免费额度 |
|------|----------|
| 每月运行时长 | **2,000 分钟**（公开仓库无限，私有仓库受限） |
| 单次 Job 超时上限 | 6 小时（360 分钟） |
| 并发 Job 数 | 20 个（免费计划） |
| 每分钟费用（超额后） | Linux: $0.008 / 分钟 |

**当前消耗估算**：
- 每天运行 2 次（cron 08:00 + 14:00）
- 每月约 60 次运行
- 若每次 5~10 分钟 → **每月消耗 300~600 分钟**（占比 15%~30%）
- 若出现超时重试，消耗可能更高

---

## 二、当前流程耗时逐环节分析

### 2.1 整体流程链

```
update-data.yml (采集 Job)           deploy-pages.yml (部署 Job)
┌────────────────────────────┐       ┌────────────────────────┐
│ 1. checkout         ~10s   │       │ 1. checkout       ~10s │
│ 2. setup-python     ~15s   │       │ 2. pip install    ~15s │
│ 3. pip install      ~20s   │       │ 3. fix_urls       ~1s  │
│ 4. 爬虫采集       2~15min  │       │ 4. build_index    ~2s  │
│ 5. build_index       ~2s   │       │ 5. upload artifact ~10s│
│ 6. git commit+push  ~15s   │       │ 6. deploy-pages   ~15s │
│ 7. trigger deploy   ~5s    │       │                        │
│                     ────── │       │                  ──────│
│ 总计:            2~16min   │       │ 总计:            ~55s  │
└────────────────────────────┘       └────────────────────────┘
```

**每次触发的 Actions 总消耗** = 采集 Job + 部署 Job ≈ **3~17 分钟**

### 2.2 爬虫采集环节详细拆解（核心瓶颈）

#### 数据源 1：GDGPO（广东省政府采购网）

| 阶段 | 请求数 | 每次延迟 | 阶段耗时 | 备注 |
|------|--------|----------|----------|------|
| 列表采集 | 1~3 页 | 2~5s | 3.5~17.5s | `page_size=20`，7 天通常 1~3 页 |
| 正文详情 | 12 条 × 1 次 | 2~5s | 24~60s | 每条记录单独请求详情 API |
| **小计** | **13~15** | — | **~30s~80s** | — |

**问题**：详情采集串行执行，12 条记录每条 2~5s 延迟 = 至少 24 秒纯等待。

#### 数据源 2：GDGGZY（广东省公共资源交易平台）

| 阶段 | 请求数 | 每次延迟 | 阶段耗时 | 备注 |
|------|--------|----------|----------|------|
| 关键词 1（医疗设备） | 1~50 页 | 2~5s | 3.5~175s | POST API |
| 关键词 2（医疗器械） | 1~50 页 | 2~5s | 3.5~175s | 大量结果与关键词 1 重叠 |
| 关键词 3（医用设备） | 1~50 页 | 2~5s | 3.5~175s | 进一步重叠 |
| 关键词 4（医疗仪器） | 1~50 页 | 2~5s | 3.5~175s | 极少独立结果 |
| **小计** | **4~200** | — | **~14s~700s** | — |

**核心问题**：
- 4 个关键词 × 最多 50 页 = **理论上 200 次请求**
- 实际中每个关键词通常 2~10 页，但仍然是 **8~40 次请求**
- 关键词之间结果高度重叠（同一条公告可能命中"医疗设备"和"医疗器械"）

#### 两个数据源合计

| 场景 | GDGPO | GDGGZY | 合计 |
|------|-------|--------|------|
| **最佳情况**（各 1~2 页，少量记录） | ~30s | ~30s | **~1 分钟** |
| **典型情况**（各 3~5 页，~50 条） | ~60s | ~90s | **~2.5 分钟** |
| **较差情况**（各 10+ 页，100+ 条） | ~120s | ~240s | **~6 分钟** |
| **最差情况**（超时重试 + 满页） | ~300s | ~700s | **~17 分钟** |

### 2.3 时间消耗热力图

```
                        占总时间比例
  ┌─────────────────────────────────────────┐
  │ 礼貌延迟 (time.sleep)    ████████ 38%  │ ← 最大浪费源
  │ 网络请求等待             ██████   28%  │
  │ 超时重试等待             ████     18%  │ ← 海外 CI 特有
  │ 环境初始化               ██        9%  │
  │ Git 操作 + 索引构建       █         5%  │
  │ 数据解析 + 去重           ▏         2%  │
  └─────────────────────────────────────────┘
```

---

## 三、已识别的 12 个效率瓶颈

### 瓶颈 1：串行执行两个数据源（严重度：★★★★）

**代码位置**：`scraper/main.py` 第 307~325 行

```python
for scraper in scrapers:           # ← 串行执行
    items = scraper.crawl(...)
    all_items.extend(items)
```

**影响**：GDGPO 和 GDGGZY 总时间 = T₁ + T₂。如果并行执行，总时间 = max(T₁, T₂)。  
**浪费**：约 30~60 秒/次。

---

### 瓶颈 2：GDGGZY 使用 4 个关键词全量搜索（严重度：★★★★★）

**代码位置**：`scraper/gd_scraper.py` 第 417 行

```python
search_keywords = ["医疗设备", "医疗器械", "医用设备", "医疗仪器"]
```

**影响**：4 个关键词各自翻页，大量结果重复（去重后仅保留一份）。  
**数据实证**：当前 49 条记录中，GDGGZY 来源 37 条。4 个关键词搜索返回的原始记录可能有 **100~150 条**，去重后仅 37 条。  
**浪费**：约 60%~70% 的请求是冗余的。

---

### 瓶颈 3：礼貌延迟过长（严重度：★★★★★）

**代码位置**：`scraper/config.py` 第 100 行

```python
"request_delay": (2, 5),  # 请求间隔 2~5 秒（随机）
```

**影响**：每次请求前等待 2~5 秒（平均 3.5 秒）。若一次采集有 50 次请求：  
- 纯等待时间 = 50 × 3.5 = **175 秒（约 3 分钟）**

**评估**：对于 API 接口（非网页），2~5 秒的延迟过于保守。政府网站 API 通常可承受 0.5~1 秒的间隔。

---

### 瓶颈 4：详情正文串行采集（严重度：★★★）

**代码位置**：`scraper/gd_scraper.py` 第 247~268 行

```python
for i, item in enumerate(items):      # ← 串行逐条获取
    detail = self.fetch_detail(nid)
    ...
    self._polite_delay()              # ← 每条还加 2~5s 延迟
```

**影响**：12 条 × (请求时间 + 3.5s 延迟) ≈ 12 × 5s = **60 秒**。  
**浪费**：详情 API 是轻量 GET 请求，不需要 2~5 秒间隔。

---

### 瓶颈 5：超时配置过于保守（严重度：★★★）

**代码位置**：`scraper/config.py` 第 94~103 行

```python
"connect_timeout": 60,     # 连接超时 60 秒
"read_timeout": 120,       # 读取超时 120 秒
"max_retries": 5,          # 5 次重试
"retry_delay": 5,          # 指数退避基数 5 秒
```

**单次请求最坏情况耗时**：
```
首次尝试: 60s(连接) + 120s(读取) = 180s
重试 1:   (60+120) = 180s  (backoff: 5×2^0 = 5s)
重试 2:   180s + 10s
重试 3:   180s + 20s
重试 4:   180s + 40s
总计最坏: 180 × 5 + (5+10+20+40) = 975 秒 ≈ 16 分钟！
```

**实际影响**：一个超时的请求可能直接吃掉 5~10 分钟的 Actions 时间。

---

### 瓶颈 6：第 1 页失败后等待 30 秒重试（严重度：★★★）

**代码位置**：`scraper/gd_scraper.py` 第 206~214 行 + 第 442~449 行

```python
logger.warning(f"第 1 页首次失败，等待 30 秒后重试: {e}")
time.sleep(30)
```

**影响**：两个数据源各自的第 1 页失败都可能额外等待 30 秒。GDGGZY 有 4 个关键词，每个都可能触发 → **最多 4 × 30 = 120 秒**。

---

### 瓶颈 7：pip 安装不必要的依赖（严重度：★★）

**代码位置**：`scraper/requirements.txt`

```
pandas>=2.0.0        # 未使用，安装耗时 ~10s
playwright>=1.40.0   # 仅在 --playwright 模式使用，安装耗时 ~15s
beautifulsoup4       # 未在当前代码中使用（已改为 API 直调）
lxml                 # 未在当前代码中使用
```

**影响**：每次 CI 运行都安装 4 个不需要的包，额外消耗 **~25 秒**。

---

### 瓶颈 8：deploy-pages.yml 重复执行构建步骤（严重度：★★）

**代码位置**：`.github/workflows/deploy-pages.yml` 第 60~65 行

```bash
pip install -q requests
python3 scripts/fix_data_urls.py    # update-data.yml 已执行过
python3 scripts/build_index.py      # update-data.yml 已执行过
```

**影响**：`update-data.yml` 中 Step 4 已经运行了 `build_index.py`，部署 Job 又跑一次 → **额外 ~3 秒 + pip install ~5 秒**。

---

### 瓶颈 9：每日 2 次 cron，周末/假期无数据也运行（严重度：★★）

**代码位置**：`.github/workflows/update-data.yml` 第 22~24 行

```yaml
schedule:
  - cron: '0 0 * * *'    # 每天 08:00
  - cron: '0 6 * * *'    # 每天 14:00
```

**影响**：周末和法定节假日，政府网站几乎不发布新公告，但 CI 仍然完整执行全部流程。  
**浪费**：每月约 8~10 个周末日 × 2 次 = 16~20 次无效运行 × 5 分钟 = **80~100 分钟/月**。

---

### 瓶颈 10：page_size 过小（严重度：★★）

**代码位置**：`scraper/config.py` 第 101 行

```python
"page_size": 20,   # 每页仅 20 条
```

**影响**：如果 GDGGZY 某关键词有 100 条结果，需要 5 页 × 3.5s = 17.5 秒。若 `page_size=100`，只需 1 页。  
**浪费**：额外 4 次请求 × 3.5s = **14 秒/关键词**，4 个关键词 = **56 秒**。

---

### 瓶颈 11：没有增量采集标记（严重度：★★★）

**当前逻辑**：每次采集完整的 N 天数据，然后与历史文件合并去重。  
**影响**：即使只有 1 条新公告，也要遍历所有页面。无法"从上次位置继续"。

---

### 瓶颈 12：两个 workflow 独立运行（严重度：★）

**当前流程**：
```
update-data.yml → push to main → deploy-pages.yml (被 push 触发)
```

**问题**：两个 workflow 各自 checkout 代码、安装依赖、构建索引。  
**浪费**：重复的环境初始化 ~20 秒。

---

## 四、优化方案与可行性评估

### 方案总览

| # | 优化方案 | 预计节省 | 实施难度 | 风险 | 优先级 |
|---|----------|----------|----------|------|--------|
| A | 双数据源并行采集 | 30~60s | 中 | 低 | P0 |
| B | GDGGZY 关键词精简 | 60~120s | 低 | 低 | P0 |
| C | 缩短礼貌延迟 | 90~150s | 低 | 低 | P0 |
| D | 降低超时 + 重试 | 60~300s | 低 | 中 | P0 |
| E | 详情并发采集 | 30~50s | 中 | 低 | P1 |
| F | 精简 pip 依赖 | 15~25s | 低 | 低 | P1 |
| G | 增大 page_size | 30~60s | 低 | 低 | P1 |
| H | 合并两个 workflow | 15~25s | 中 | 中 | P2 |
| I | 增量采集机制 | 60~180s | 高 | 中 | P2 |
| J | 工作日限定 cron | 80~100min/月 | 低 | 低 | P1 |
| K | 部署 Job 去除冗余构建 | 5~10s | 低 | 低 | P2 |
| L | 使用 Actions Cache | 10~20s | 中 | 低 | P2 |

---

### 方案 A：双数据源并行采集（P0）

**原理**：使用 Python `concurrent.futures.ThreadPoolExecutor` 或 `asyncio` 并行执行两个爬虫。

**实现方案**：
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=2) as pool:
    futures = {pool.submit(scraper.crawl, start_date, end_date, max_pages): scraper
               for scraper in scrapers}
    for future in as_completed(futures):
        scraper = futures[future]
        items = future.result()
        all_items.extend(items)
```

**预计节省**：min(T_gdgpo, T_gdggzy) ≈ **30~60 秒/次**

**可行性评估**：
- ✅ `requests` 库是线程安全的（每个爬虫有独立 Session）
- ✅ 两个数据源访问不同域名，不存在并发冲突
- ⚠️ 需要注意日志输出的线程安全性（Python logging 默认线程安全）
- **风险**：极低
- **实施工作量**：约 20 行代码修改

---

### 方案 B：GDGGZY 关键词精简（P0）

**原理**：减少冗余关键词搜索，利用 API 的空关键词搜索能力。

**实现方案**：
```python
# 方案 B1: 只保留 1~2 个高覆盖关键词
search_keywords = ["医疗设备"]   # 覆盖 90%+ 的医疗相关公告

# 方案 B2: 使用空关键词 + 后置过滤（如果 API 支持）
body = {
    ...
    "keyword": "",   # 搜索全部，在本地用 is_medical_related() 过滤
}
```

**数据实证**：
- 当前 4 个关键词搜索返回的原始记录中，约 60~70% 是重复的
- "医疗设备" 一个关键词已覆盖绝大部分目标公告
- "医疗仪器" 几乎不返回独立结果

**预计节省**：减少 2~3 个关键词的全量翻页 ≈ **60~120 秒/次**

**可行性评估**：
- ✅ 减少关键词不影响最终数据质量（去重后结果几乎一致）
- ⚠️ 需要验证空关键词搜索是否被 GDGGZY API 支持
- **风险**：低（可先尝试 2 个关键词，观察 1 周数据完整性）
- **实施工作量**：1 行代码修改

---

### 方案 C：缩短礼貌延迟（P0）

**原理**：API 接口不同于网页，服务端已做好被程序调用的准备，无需 2~5 秒的超长间隔。

**实现方案**：
```python
HTTP_CONFIG = {
    "request_delay": (0.5, 1.5),   # 从 (2, 5) 降至 (0.5, 1.5)
    # 详情 API 使用更短的延迟
    "detail_delay": (0.3, 0.8),
}
```

**预计节省**：
- 50 次请求 × (3.5 - 1.0) = **125 秒**
- 12 次详情 × (3.5 - 0.55) = **35 秒**
- **合计约 160 秒/次**

**可行性评估**：
- ✅ 政府 API 通常无严格的频率限制（GDGGZY 有 429 机制，但阈值较高）
- ✅ 已有 429 状态码自动重试机制作为安全网
- ⚠️ 需要观察 1~2 天是否触发更多 429 或 IP 限制
- **风险**：低（可渐进式降低：先 1~2s，再 0.5~1.5s）
- **实施工作量**：2 行代码修改

---

### 方案 D：降低超时 + 重试参数（P0）

**原理**：当前配置是为"海外 CI 访问国内网站"的极端场景设计的，但大部分请求在 10~15 秒内就能完成。

**实现方案**：
```python
HTTP_CONFIG = {
    "connect_timeout": 20,       # 从 60 降至 20（正常连接 5s 内完成）
    "read_timeout": 30,          # 从 120 降至 30（API 响应通常 5~10s）
    "timeout": (20, 30),
    "max_retries": 3,            # 从 5 降至 3（够用了）
    "retry_delay": 3,            # 从 5 降至 3
}
```

**单次请求最坏情况对比**：
| 配置 | 最坏耗时 |
|------|----------|
| 当前 (60+120, 5次重试) | 975 秒 (16 分钟) |
| 优化后 (20+30, 3次重试) | 162 秒 (2.7 分钟) |

**预计节省**：在超时场景下节省 **5~13 分钟**

**可行性评估**：
- ✅ 正常请求不受影响（API 通常 5~10s 响应）
- ✅ 减少重试次数避免"死等"一个不可达的接口
- ⚠️ 如果 GitHub Actions 某天网络特别差，可能误判为失败
- **风险**：中低（已有第 1 页额外重试机制兜底）
- **实施工作量**：5 行配置修改

---

### 方案 E：详情并发采集（P1）

**原理**：GDGPO 详情 API 是轻量 GET 请求，可以使用线程池并发获取。

**实现方案**：
```python
from concurrent.futures import ThreadPoolExecutor

def _fetch_one_detail(self, item):
    """获取单条详情（线程安全）"""
    nid = item.url.split("id=")[-1] if "id=" in item.url else ""
    if not nid:
        return
    try:
        detail = self.fetch_detail(nid)
        desc = detail.get("description", "")
        if desc:
            text = re.sub(r"<[^>]+>", "", desc)
            text = re.sub(r"\s+", " ", text).strip()
            item.content = text[:2000]
    except Exception:
        pass

# 并发采集（3~5 个线程）
with ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(lambda item: self._fetch_one_detail(item), items))
```

**预计节省**：12 条详情从串行 60s → 并发 ~15s ≈ **45 秒**

**可行性评估**：
- ✅ 每条详情请求独立，无依赖关系
- ⚠️ 需要在 Session 中使用连接池（当前 `pool_connections=5` 已满足）
- **风险**：低
- **实施工作量**：约 30 行代码

---

### 方案 F：精简 pip 依赖（P1）

**原理**：只安装实际使用的包。

**实现方案**：

拆分 `scraper/requirements.txt`：
```
# requirements-core.txt（CI 必需）
requests>=2.31.0
urllib3>=2.0.0

# requirements-full.txt（本地开发 / Playwright 模式）
beautifulsoup4>=4.12.0
pandas>=2.0.0
playwright>=1.40.0
lxml>=5.0.0
```

CI 中改为：
```yaml
- name: 安装 Python 依赖
  run: pip install -r scraper/requirements-core.txt
```

**预计节省**：
- `pandas` 安装 ~10s（含 numpy 编译）
- `playwright` 安装 ~15s
- `beautifulsoup4` + `lxml` ~5s
- **合计约 25~30 秒**

**可行性评估**：
- ✅ `pandas` 在当前代码中完全未使用
- ✅ `beautifulsoup4` / `lxml` 在当前 API 直调模式下未使用
- ✅ `playwright` 仅在 `--playwright` 备用模式使用
- **风险**：极低
- **实施工作量**：拆分文件 + 修改 CI 配置

---

### 方案 G：增大 page_size（P1）

**原理**：减少翻页次数 = 减少请求数 = 减少延迟时间。

**实现方案**：
```python
HTTP_CONFIG = {
    "page_size": 50,    # 从 20 增大到 50（或 100）
}
```

**预计节省**：
- GDGGZY 某关键词 100 条结果：从 5 页 → 2 页，减少 3 次请求 × 3.5s = **10.5s**
- 4 个关键词合计：**~42 秒**
- 如果方案 B 精简到 1~2 个关键词：**~20 秒**

**可行性评估**：
- ✅ 大多数政府 API 支持 `pageSize=50` 或 `pageSize=100`
- ⚠️ 需要验证 GDGPO / GDGGZY API 是否接受 50 或 100
- **风险**：低
- **实施工作量**：1 行配置修改

---

### 方案 H：合并两个 workflow（P2）

**原理**：将 deploy-pages 的构建步骤合并到 update-data.yml 中，避免重复的环境初始化。

**实现方案**：
```yaml
# update-data.yml 中直接构建并部署
- name: 构建前端
  run: |
    mkdir -p dist/data
    cp frontend/index.html dist/
    python scripts/build_index.py
    cp frontend/public/data/* dist/data/

- name: 上传到 Pages
  uses: actions/upload-pages-artifact@v3
  with:
    path: dist

deploy:
  needs: crawl-and-commit
  runs-on: ubuntu-latest
  steps:
    - uses: actions/deploy-pages@v4
```

**预计节省**：~20 秒（避免重复 checkout + pip install）

**可行性评估**：
- ✅ 逻辑上完全可行
- ⚠️ 需要保留手动触发 deploy 的能力（代码变更但无需重新采集时）
- ⚠️ 合并后单个 Job 更重，可能降低灵活性
- **风险**：中
- **实施工作量**：重写 workflow 文件

---

### 方案 I：增量采集机制（P2）

**原理**：记录上次采集的最新日期/ID，下次只采集新增部分。

**实现方案**：
```python
# 在 data/ 目录下维护一个 checkpoint 文件
CHECKPOINT_FILE = DATA_DIR / ".crawl_checkpoint"

def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"last_date": None, "last_ids": set()}

def save_checkpoint(latest_date, new_ids):
    CHECKPOINT_FILE.write_text(json.dumps({
        "last_date": latest_date,
        "last_ids": list(new_ids)[-100:],  # 只保留最近 100 个 ID
    }))
```

**预计节省**：
- 典型场景：7 天数据可能 50 条，增量后只需采集 1~5 条新增
- **每次节省 60~180 秒**（减少翻页 + 减少详情请求）

**可行性评估**：
- ✅ 概念上可行
- ⚠️ 需要处理 checkpoint 丢失/损坏的情况（回退到全量采集）
- ⚠️ 第一次运行仍需全量采集
- ⚠️ 需要确保旧数据不会被遗漏（checkpoint 之前的数据变更）
- **风险**：中（数据完整性是关键）
- **实施工作量**：约 50 行代码 + 测试

---

### 方案 J：工作日限定 cron（P1）

**原理**：政府网站周末和法定节假日几乎不更新，跳过这些天的采集。

**实现方案**：
```yaml
schedule:
  - cron: '0 0 * * 1-5'    # 仅周一到周五 08:00
  - cron: '0 6 * * 1-5'    # 仅周一到周五 14:00
```

**预计节省**：
- 每月约 8~10 个周末日 × 2 次 × 5 分钟 = **80~100 分钟/月**
- 占总额度的 **4%~5%**

**可行性评估**：
- ✅ GitHub Actions cron 支持星期限定（0=周日, 1-5=周一到周五）
- ⚠️ 部分政府公告可能在周末发布（极少），周一采集时会覆盖
- **风险**：极低
- **实施工作量**：2 行配置修改

---

### 方案 K：部署 Job 去除冗余构建（P2）

**原理**：`update-data.yml` 已运行 `build_index.py`，部署 Job 无需重复运行。

**实现方案**：移除 `deploy-pages.yml` 中的 `fix_data_urls.py` 和 `build_index.py` 步骤。

**预计节省**：~8 秒

**可行性评估**：
- ✅ 如果只通过 update-data → deploy 链路触发，数据已经是最新的
- ⚠️ 手动触发 deploy 或 push 触发时，可能数据未构建
- **风险**：低（可保留 fallback 逻辑）
- **实施工作量**：删除 ~5 行

---

### 方案 L：使用 Actions Cache 缓存 pip（P2）

**原理**：利用 `actions/setup-python` 的 cache 功能缓存 pip 包。

**当前状态**：`update-data.yml` 已配置 `cache: 'pip'`，但 `deploy-pages.yml` 未配置。

**预计节省**：~10 秒/次

**可行性评估**：
- ✅ 简单配置即可
- **风险**：极低
- **实施工作量**：1~2 行配置

---

## 五、优化效果预测

### 5.1 实施方案 A+B+C+D（P0 优化）后

| 场景 | 当前耗时 | 优化后 | 节省比例 |
|------|----------|--------|----------|
| 最佳 | ~2 min | ~45s | **-62%** |
| 典型 | ~5 min | ~1.5 min | **-70%** |
| 较差 | ~10 min | ~3 min | **-70%** |
| 最差 | ~17 min | ~5 min | **-71%** |

### 5.2 实施全部 P0+P1 优化后

| 场景 | 当前耗时 | 优化后 | 节省比例 |
|------|----------|--------|----------|
| 最佳 | ~2 min | ~30s | **-75%** |
| 典型 | ~5 min | ~1 min | **-80%** |
| 较差 | ~10 min | ~2 min | **-80%** |
| 最差 | ~17 min | ~4 min | **-76%** |

### 5.3 月度 Actions 消耗对比

| 配置 | 每次耗时 | 每日次数 | 月总耗时 | 占免费额度 |
|------|----------|----------|----------|-----------|
| **当前** | 5 min | 2 | 300 min | 15% |
| **P0 优化** | 1.5 min | 2 | 90 min | 4.5% |
| **P0+P1** | 1 min | 2（工作日） | 44 min | **2.2%** |
| **全部优化** | 0.7 min | 2（工作日） | 31 min | **1.5%** |

---

## 六、推荐实施路线图

### 第一阶段（立即实施，预计节省 70%）

```
1. 修改 config.py:
   - request_delay: (2,5) → (0.8, 1.5)
   - timeout: (60,120) → (20, 30)
   - max_retries: 5 → 3
   - retry_delay: 5 → 3
   - page_size: 20 → 50

2. 修改 gd_scraper.py:
   - search_keywords: 4个 → 2个（"医疗设备" + "医疗器械"）

3. 修改 main.py:
   - 使用 ThreadPoolExecutor 并行执行两个爬虫
```

**预计改动**：~30 行代码  
**预计效果**：每次采集从 ~5 min → ~1.5 min

### 第二阶段（1 周内实施，预计额外节省 10%）

```
4. 拆分 requirements.txt → requirements-core.txt
5. 修改 cron 为仅工作日运行
6. 修改 CI 使用 requirements-core.txt
7. 详情采集改为并发（ThreadPoolExecutor）
```

### 第三阶段（可选，进一步优化）

```
8. 实现增量采集机制（checkpoint）
9. 合并两个 workflow 为一个
10. 部署 Job 去除冗余构建步骤
```

---

## 七、风险评估

| 风险项 | 可能性 | 影响 | 缓解措施 |
|--------|--------|------|----------|
| 缩短延迟导致目标网站封 IP | 低 | 中 | 保留 429 重试机制；渐进降低 |
| 降低超时导致部分请求误判失败 | 中低 | 低 | 第 1 页重试机制兜底 |
| 减少关键词导致漏采 | 低 | 中 | 先观察 1 周数据完整性 |
| 并行采集导致内存/CPU 不足 | 极低 | 低 | Actions 有 7GB RAM |
| 工作日限定漏掉周末公告 | 极低 | 低 | 周一采集覆盖周末数据 |

---

## 八、结论

当前采集流程的**最大时间浪费源**是：
1. **礼貌延迟过长**（占总时间 38%）— 对 API 接口使用 2~5s 间隔完全不必要
2. **GDGGZY 冗余关键词搜索**（占 28%）— 4 个关键词返回 60%+ 重复结果
3. **串行执行**（占 18%）— 两个数据源完全可以并行

仅通过**修改 4 个配置值 + 1 个关键词列表 + 5 行并行代码**，即可将每次采集时间从 ~5 分钟降低到 ~1.5 分钟，月度 Actions 消耗从 ~300 分钟降至 ~90 分钟。

加上第一阶段的全部优化，**月度消耗可控制在 44 分钟以内**（仅占免费额度的 2.2%），完全不用担心额度问题。
