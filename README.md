# 粤采雷达 GD-MedProcure-Radar

> 广东省医疗设备采购信息自动采集与展示系统

[![数据采集](https://github.com/YOUR_USERNAME/GD-MedProcure-Radar/actions/workflows/update-data.yml/badge.svg)](https://github.com/YOUR_USERNAME/GD-MedProcure-Radar/actions/workflows/update-data.yml)
[![部署 Pages](https://github.com/YOUR_USERNAME/GD-MedProcure-Radar/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/YOUR_USERNAME/GD-MedProcure-Radar/actions/workflows/deploy-pages.yml)

## 项目简介

**粤采雷达**是一个全自动的医疗设备采购信息监测系统。它每天定时从广东省政府采购网和公共资源交易平台采集最新的采购公告，自动清洗去重后，以可视化网页的形式展示，支持按地区、医院、项目编号、类目进行搜索和筛选。

**核心能力：**
- 每天 08:00 / 14:00（北京时间）自动采集最新采购数据
- 跨数据源自动去重（政府采购网 + 公共资源交易平台）
- 纯前端离线全文搜索（FlexSearch），无需后端服务器
- 部署到 GitHub Pages，零成本运行

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 爬虫引擎 | Python 3.10+ / Requests | REST API 直接调用，无需浏览器渲染 |
| 定时调度 | GitHub Actions | Cron 定时 + 手动触发 |
| 数据处理 | Python / Pandas | 清洗、去重、聚合统计 |
| 搜索索引 | FlexSearch | 前端离线全文搜索引擎 |
| 前端界面 | HTML5 + TailwindCSS + Alpine.js | 单文件 SPA，CDN 引入，无需构建 |
| 部署 | GitHub Pages | 纯静态文件，无需服务器 |

## 数据源

| 数据源 | 网址 | API 方式 |
|--------|------|---------|
| 广东省政府采购网 | gdgpo.czt.gd.gov.cn | `GET /gpcms/rest/web/v2/info/selectInfoForIndex` |
| 广东省公共资源交易平台 | ygp.gdzwfw.gov.cn | `POST /ggzy-portal/search/v2/items` |

## 项目结构

```
GD-MedProcure-Radar/
├── scraper/                        # Python 爬虫引擎
│   ├── config.py                   #   全局配置（API地址、请求头、关键词）
│   ├── gd_scraper.py               #   核心爬虫（GDGPO + GDGGZY 两个数据源）
│   ├── main.py                     #   调度入口（采集 → 去重 → 合并 → 保存）
│   └── requirements.txt            #   Python 依赖
├── scripts/
│   └── build_index.py              # 搜索索引与聚合数据构建
├── frontend/
│   ├── index.html                  # 前端单页应用（全部代码在此文件）
│   └── public/data/                # 前端数据文件
│       ├── procurements.json       #   采购详情（完整字段）
│       ├── aggregations.json       #   聚合统计（筛选用）
│       └── search-index.json       #   FlexSearch 索引
├── data/
│   ├── procurements.json           # 主数据文件
│   ├── aggregations.json           # 聚合统计
│   └── raw/                        # 原始采集快照
├── .github/workflows/
│   ├── update-data.yml             # 数据采集工作流（Cron + 手动）
│   └── deploy-pages.yml            # 前端部署工作流
├── Docs/                           # 设计报告文档
│   ├── 01-架构设计报告.md
│   ├── 02-爬虫开发报告.md
│   ├── 03-GitHub-Actions配置报告.md
│   ├── 04-搜索索引构建报告.md
│   ├── 05-前端界面开发报告.md
│   └── 06-部署使用教程.md
├── reference/                      # 前期市场调研资料
├── AGENTS.md                       # Qoder 工作指引
├── .gitignore
└── README.md
```

## 快速开始

### 环境要求

- **Python** 3.10 或更高版本
- **Git**（用于克隆仓库和提交代码）

### 安装依赖

```bash
pip install -r scraper/requirements.txt
```

### 本地运行爬虫

```bash
# 测试模式（只采集少量数据）
python -m scraper --test

# 完整采集（默认近 7 天）
python -m scraper

# 指定数据源
python -m scraper --source gdgpo
python -m scraper --source gdggzy

# 指定天数
python -m scraper --days 14

# 跳过正文采集（更快）
python -m scraper --no-content
```

### 构建搜索索引

```bash
python scripts/build_index.py
```

### 本地预览前端

```bash
# 方式一：组装测试目录后启动
mkdir test-serve\data
copy frontend\index.html test-serve\
copy frontend\public\data\* test-serve\data\
cd test-serve
python -m http.server 8080
# 浏览器打开 http://localhost:8080

# 方式二：直接打开文件（功能可能受限）
# 在浏览器中打开 frontend/index.html
```

## 自动化流程

整个项目通过 GitHub Actions 实现全自动化：

```
每天 08:00 / 14:00（北京时间）
    ↓
[update-data.yml] 运行 Python 爬虫
    ↓
采集广东省政府采购网 + 公共资源交易平台数据
    ↓
数据清洗、去重、合并
    ↓
[build_index.py] 构建搜索索引 + 聚合统计
    ↓
Git commit + push（数据文件）
    ↓
触发 [deploy-pages.yml]
    ↓
复制 index.html + 数据 → 部署到 GitHub Pages
    ↓
用户访问网站查看最新数据
```

## 开发文档

每一步开发过程都有详细的技术报告：

| 编号 | 文档 | 内容 |
|------|------|------|
| 01 | [架构设计报告](Docs/01-架构设计报告.md) | 项目整体架构、目录结构、技术选型 |
| 02 | [爬虫开发报告](Docs/02-爬虫开发报告.md) | 目标网站分析、API 逆向、爬虫实现 |
| 03 | [GitHub Actions 配置报告](Docs/03-GitHub-Actions配置报告.md) | CI/CD 工作流、Token 配置 |
| 04 | [搜索索引构建报告](Docs/04-搜索索引构建报告.md) | 聚合统计、FlexSearch 索引生成 |
| 05 | [前端界面开发报告](Docs/05-前端界面开发报告.md) | 单页应用、搜索策略、UI 设计 |
| 06 | [部署使用教程](Docs/06-部署使用教程.md) | 从零开始的完整部署指南 |
| 07 | [详情链接修复与公告内容采集](Docs/07-详情链接修复与公告内容采集.md) | URL 修复、正文采集、前端展示 |
| 08 | [0610 详情页弹窗与 URL 修复](Docs/08-0610详情页与URL修复.md) | 详情弹窗、URL 三层修复、CI 增强 |
| 09 | [GitHub Actions 采集效率优化报告](Docs/09-GitHub-Actions采集效率优化报告.md) | 12 个效率瓶颈分析、优化方案与可行性评估 |
| 10 | [采集效率优化实施报告](Docs/10-采集效率优化实施报告.md) | P0/P1/P2 全部实施记录、效果对比、验证报告 |

## 许可证

本项目仅供信息参考，不构成任何商业建议。
