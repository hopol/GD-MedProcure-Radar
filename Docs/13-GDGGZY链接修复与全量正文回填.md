# 粤采雷达 - GDGGZY 链接修复与全量正文回填报告

**编号**: 13  
**日期**: 2026-06-05  
**性质**: 链接稳定性优化 + 正文内容全量回填  

---

## 一、问题描述

用户反馈两个问题：

| # | 问题 | 影响 |
|---|------|------|
| 1 | GDGGZY（ygp.gdzwfw.gov.cn）链接打开后显示首页，无法定位到具体公告 | 37 条链接全部受影响 |
| 2 | 部分公告在原网站已被下架，打开后跳转到首页 | 源站行为，无法控制 |

---

## 二、根因分析

### 2.1 URL 参数过多导致 SPA 路由不稳定

GDGGZY 是 Vue SPA 应用，使用 hash 路由（`#/`）。原 URL 包含 8 个查询参数：

```
https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/D?noticeId=xxx&projectCode=xxx&bizCode=xxx&siteCode=xxx&publishDate=xxx&source=xxx&titleDetails=xxx&classify=xxx
```

通过逆向分析 GDGGZY 前端 JS bundle（`index-f1c6abff.js`），确认路由定义为：

```
path: "/new/jygg/:edition(v1|v2|v3)/:tradingType"
```

**路由只使用路径参数**（`edition` 和 `tradingType`），其余参数通过 query string 传递。过多参数在某些浏览器/环境下会导致 SPA 解析异常。

### 2.2 部分公告已被原网站下架

GDGGZY 平台会定期清理过期公告。已下架的公告链接打开后，SPA 找不到对应记录，回退显示首页。

---

## 三、修复方案

### 3.1 URL 精简（提高链接稳定性）

**方案**：去掉所有冗余参数，只保留核心 `noticeId`。

| 修改前 | 修改后 |
|--------|--------|
| `...?noticeId=xxx&projectCode=xxx&bizCode=xxx&siteCode=xxx&publishDate=xxx&source=xxx&titleDetails=xxx&classify=xxx` | `...?noticeId=xxx` |

**修改文件**：

| 文件 | 修改 |
|------|------|
| `scraper/config.py` | `detail_url_template` 精简为只含 `noticeId` |
| `scraper/gd_scraper.py` | URL 构建逻辑同步精简 |
| `scripts/fix_data_urls.py` | CI 部署时自动精简 URL |
| `data/procurements.json` | 37 条现有 URL 全部精简 |

### 3.2 全量正文回填（不再依赖外链）

**方案**：即使外链失效，弹窗内也能显示完整的公告信息。

- **GDGPO（12 条）**：通过 `getInfoById` API 获取 HTML 正文 → 清洗为纯文本 → 存入 `content`
- **GDGGZY（37 条）**：从搜索结果字段构建结构化摘要 → 存入 `content`

### 3.3 爬虫升级（未来采集自动生成正文）

GDGGZY 爬虫 `_parse_record()` 新增摘要构建逻辑：采集时自动从搜索记录提取标题、采购人、项目编号、地区、日期、类型等字段，组合为结构化正文。

### 3.4 前端弹窗优化

- GDGGZY 无正文时显示"该公告原文可能已被下架"（替代"正文内容暂未采集"）
- 提示用户点击右下方"访问原始网页"按钮

---

## 四、修改文件清单

| 文件 | 操作 | 修改内容 |
|------|------|----------|
| `scraper/config.py` | 修改 | URL 模板精简为只含 noticeId |
| `scraper/gd_scraper.py` | 修改 | URL 构建精简 + 搜索结果存为 content |
| `scripts/fix_data_urls.py` | 修改 | 新增 URL 精简逻辑（CI 自动执行） |
| `scripts/backfill_gdggzy_content.py` | **新建** | GDGGZY 正文回填脚本 |
| `frontend/index.html` | 修改 | 弹窗下架提示 + 右下方按钮引导 |
| `data/procurements.json` | 数据更新 | 37 条 URL 精简 + 37 条正文回填 |
| `frontend/public/data/*` | 数据更新 | 重建搜索索引和数据副本 |

---

## 五、验证结果

### 5.1 数据验证

```
总计: 49 条
GDGPO:  12 条, 有正文: 12/12 (100%) ✅
GDGGZY: 37 条, 有正文: 37/37 (100%) ✅
        精简 URL: 37/37 (100%) ✅
```

### 5.2 语法验证

| 文件 | py_compile |
|------|-----------|
| `scraper/config.py` | ✅ 通过 |
| `scraper/gd_scraper.py` | ✅ 通过 |
| `scripts/fix_data_urls.py` | ✅ 通过 |
| `scripts/backfill_gdggzy_content.py` | ✅ 通过 |

### 5.3 正文示例

**GDGPO 正文**（API 获取的完整正文）：
> 项目概况 阳江市人民医院数字减影血管成像系统（DSA）采购项目(二次)招标项目的潜在投标人应在广东省政府采购网获取招标文件...

**GDGGZY 正文**（结构化摘要）：
> 公告标题：南方医科大学珠江医院医疗设备采购项目（麻醉机、监护仪...）的合同公告  
> 采购人：南方医科大学珠江医院  
> 项目编号：0809-26411GDG103005601  
> 地区：省级  
> 发布日期：2026-06-05  
> 公告类型：政府采购  
> 数据集：合同公告  

---

## 六、关于已下架公告

部分 GDGGZY 公告在原网站已被下架，表现为：
- 点击"访问原始网页"后显示 GDGGZY 首页
- 这是**源站行为**，无法从我们这边修复

**应对策略**：
- 弹窗内已显示公告的完整结构化信息（标题、采购人、编号、日期等）
- 即使外链失效，用户仍可获取关键信息
- 未来 CI 采集时，新数据会自动包含 content 字段

---

## 七、后续维护

### 7.1 CI 自动修复

`deploy-pages.yml` 在每次部署时自动运行 `fix_data_urls.py`，确保：
- GDGPO 旧格式 URL 被修正
- GDGGZY URL 被精简为只含 noticeId
- HTTP URL 被升级为 HTTPS

### 7.2 手动回填

如需重新回填正文内容：

```bash
python scripts/backfill_gdggzy_content.py
python scripts/build_index.py
```
