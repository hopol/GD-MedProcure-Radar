# 粤采雷达 - GitHub Actions CI/CD 配置报告

> **文档编号**：GD-MPR-CICD-003  
> **版本**：v1.0  
> **编制时间**：2026 年 6 月 5 日  
> **阶段**：Step 3 — CI/CD 工作流配置

---

## 1. 工作流总览

本阶段创建了两个 GitHub Actions 工作流文件：

| 文件 | 用途 | 触发方式 |
|------|------|----------|
| `.github/workflows/update-data.yml` | 数据采集与提交 | Cron 定时 / 手动 |
| `.github/workflows/deploy-pages.yml` | 前端构建与部署 | push 数据变更 / 手动 / 被上游触发 |

### 协作流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                  update-data.yml (数据采集)                       │
│                                                                 │
│  触发: Cron 08:00/14:00 北京时间 │ workflow_dispatch (手动)       │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Checkout │→ │ Python   │→ │ 运行爬虫  │→ │ Git Commit    │   │
│  │ 代码     │  │ Setup +  │  │ python -m │  │ + Push (仅当  │   │
│  │          │  │ pip      │  │ scraper   │  │ 数据有变更)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └───────┬───────┘   │
│                                                     │           │
│                                                     ▼           │
│                                            ┌────────────────┐   │
│                                            │ 触发            │   │
│                                            │ deploy-pages   │   │
│                                            │ (API dispatch) │   │
│                                            └────────┬───────┘   │
└─────────────────────────────────────────────────────┼───────────┘
                                                      │
                                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                  deploy-pages.yml (前端部署)                      │
│                                                                 │
│  触发: push data/procurements.json │ workflow_dispatch │ 上游API │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Checkout │→ │ Node.js  │→ │ npm build │→ │ Deploy Pages  │   │
│  │ 代码     │  │ Setup +  │  │ 复制数据  │  │ (gh-pages)    │   │
│  │          │  │ npm ci   │  │ 到 public │  │               │   │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. update-data.yml 详解

### 2.1 触发条件

```yaml
on:
  schedule:
    - cron: '0 0 * * *'    # 北京时间 08:00 = UTC 00:00
    - cron: '0 6 * * *'    # 北京时间 14:00 = UTC 06:00
  workflow_dispatch:
    inputs:
      days: ...       # 采集天数
      source: ...     # 数据源选择
      skip_deploy: ... # 是否跳过部署
```

**时区转换**：GitHub Actions 的 Cron 使用 UTC 时间。北京时间 = UTC + 8 小时。

| 北京时间 | UTC 时间 | Cron 表达式 |
|----------|----------|-------------|
| 08:00 | 00:00 | `0 0 * * *` |
| 14:00 | 06:00 | `0 6 * * *` |

### 2.2 手动触发参数

通过 `workflow_dispatch` 支持以下可配置参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `days` | string | `7` | 采集近 N 天数据 |
| `source` | choice | `""` (全部) | 指定数据源 `gdgpo` / `gdggzy` |
| `skip_deploy` | boolean | `false` | 跳过前端部署触发 |

### 2.3 执行步骤

```
Step 1: Checkout 代码 (actions/checkout@v4)
  └─ 使用 GH_PAT 或 GITHUB_TOKEN 鉴权

Step 2: 配置 Python (actions/setup-python@v5)
  └─ 启用 pip 缓存，加速依赖安装

Step 3: 安装依赖 (pip install -r scraper/requirements.txt)

Step 4: 运行爬虫 (python -m scraper $ARGS)
  └─ 根据触发方式构建参数
  └─ 记录退出码和输出到 GITHUB_OUTPUT
  └─ 统计采集记录数

Step 5: 检查并提交 (git diff --cached --quiet)
  └─ 仅当数据文件有实际变更时才提交
  └─ 提交信息包含记录数、时间、触发方式

Step 6: 推送 (git push origin HEAD:main)
  └─ rebase 策略避免冲突
  └─ 失败时回退到 merge 策略

Step 7: 触发部署 (actions/github-script@v7)
  └─ 通过 GitHub API 调用 deploy-pages.yml
  └─ 工作流不存在时仅警告不失败

Step 8: 输出摘要 (GITHUB_STEP_SUMMARY)
  └─ Markdown 格式的可视化报告
```

### 2.4 并发控制

```yaml
concurrency:
  group: data-crawl
  cancel-in-progress: true
```

同一时间只允许一个采集任务运行，新触发会自动取消正在运行的旧任务。

---

## 3. deploy-pages.yml 详解

### 3.1 三重触发机制

| 触发方式 | 场景 |
|----------|------|
| `workflow_dispatch` | 被 `update-data.yml` 通过 API 触发，或手动触发 |
| `push` on `data/procurements.json` | 当数据文件被推送到 main 时自动触发（备用） |
| 手动触发 | 在 GitHub 仓库页面点击 "Run workflow" |

### 3.2 构建与部署流程

```
Job 1: build (构建)
  ├─ checkout 代码
  ├─ setup Node.js 20 + npm cache
  ├─ 复制 data/procurements.json → frontend/public/data/
  ├─ npm ci (安装依赖)
  ├─ npm run build (构建)
  └─ upload-pages-artifact (上传 dist/)

Job 2: deploy (部署, needs: build)
  └─ actions/deploy-pages@v4 → GitHub Pages
```

---

## 4. Token 与权限最佳实践

### 4.1 核心问题

GitHub Actions 的默认 `GITHUB_TOKEN` 存在一个关键限制：**使用该 Token 触发的 push 事件不会激活其他工作流**。这意味着如果 `update-data.yml` 用 `GITHUB_TOKEN` 推送数据提交，`deploy-pages.yml` 的 `push` 触发器不会被激活。

### 4.2 解决方案

**推荐方案：使用 Fine-grained Personal Access Token (PAT)**

| 方案 | Token 类型 | 可触发下游工作流 | 安全性 |
|------|-----------|:---:|:---:|
| **推荐** | Fine-grained PAT | ✅ | ⭐⭐⭐ |
| 备选 | Classic PAT (`repo`) | ✅ | ⭐⭐ |
| 兜底 | GITHUB_TOKEN | ❌ (仅 push 触发) | ⭐⭐⭐ |

### 4.3 PAT 配置步骤

1. 前往 **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. 点击 **Generate new token**
3. 配置：
   - **Token name**: `GD-MEDPROCURE-RADAR-CI`
   - **Expiration**: 选择合适有效期（建议 90 天，到期续签）
   - **Repository access**: 仅选择 `GD-MedProcure-Radar` 仓库
   - **Permissions → Repository**:
     - `Contents`: Read and write（推送数据提交）
     - `Actions`: Read and write（触发工作流）
4. 生成后，前往仓库 **Settings → Secrets and variables → Actions**
5. 点击 **New repository secret**
6. **Name**: `GH_PAT`，**Value**: 粘贴 Token 值

### 4.4 工作流中的 Token 使用

```yaml
# checkout 时使用 PAT（确保后续 push 能触发下游）
- uses: actions/checkout@v4
  with:
    token: ${{ secrets.GH_PAT || secrets.GITHUB_TOKEN }}

# API 调用时使用 PAT（触发 workflow_dispatch）
- uses: actions/github-script@v7
  with:
    github-token: ${{ secrets.GH_PAT || secrets.GITHUB_TOKEN }}
```

使用 `${{ secrets.GH_PAT || secrets.GITHUB_TOKEN }}` 的**回退策略**：
- 如果配置了 `GH_PAT`，使用它（完整功能）
- 如果未配置，回退到 `GITHUB_TOKEN`（基本功能，但部署工作流需依赖 `push` 触发）

### 4.5 权限声明

```yaml
permissions:
  contents: write    # update-data: 推送提交
  actions: write     # update-data: 触发下游工作流

permissions:
  contents: read     # deploy-pages: 读取代码
  pages: write       # deploy-pages: 部署到 Pages
  id-token: write    # deploy-pages: Pages 部署认证
```

---

## 5. 数据提交策略

### 5.1 变更检测

```bash
git add data/procurements.json
if git diff --cached --quiet; then
  # 无变更 → 跳过提交
else
  # 有变更 → 提交并推送
fi
```

**关键点**：
- `.gitignore` 中 `data/raw/*.json` 被忽略，所以原始快照不会被提交
- 只有 `data/procurements.json`（最终去重数据）会被追踪和提交
- 如果本次采集的数据与已有数据完全相同（无新增），不会产生无意义的提交

### 5.2 提交信息格式

```
📊 数据更新: 312 条记录 (2026-06-05 08:15 UTC)

采集参数: --days 7
触发方式: schedule
记录数量: 312

Co-authored-by: github-actions[bot] <41898282+...>
```

### 5.3 冲突处理

```bash
# 优先 rebase（保持线性历史）
git pull --rebase origin main || {
  # rebase 冲突时回退到 merge
  git rebase --abort
  git pull --no-edit origin main
}
git push origin HEAD:main
```

---

## 6. GitHub Pages 部署前置配置

在部署工作流生效前，需要在仓库中完成以下配置：

### 6.1 启用 GitHub Pages

1. 前往仓库 **Settings → Pages**
2. **Source** 选择 **GitHub Actions**（非 "Deploy from a branch"）
3. 保存设置

### 6.2 前端项目准备

确保 `frontend/` 目录下有：
- `package.json` — 包含 `build` 脚本
- `vite.config.js` — 配置正确的 `base` 路径

```javascript
// vite.config.js 示例
export default defineConfig({
  base: '/GD-MedProcure-Radar/',  // 仓库名作为 base path
  build: {
    outDir: 'dist',
  },
})
```

---

## 7. 监控与排障

### 7.1 查看运行日志

- **GitHub Web**: 仓库 → Actions 标签页 → 选择工作流运行记录
- **Job Summary**: 每次运行都会生成 Markdown 格式的摘要报告

### 7.2 常见问题排查

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| `push rejected` | 并发提交冲突 | 已内置 rebase + merge 回退策略 |
| `403 Forbidden` on push | Token 权限不足 | 检查 `GH_PAT` 是否配置且有 Contents 写权限 |
| 爬虫超时 | 目标网站响应慢 | 调整 `scraper/config.py` 中的 `timeout` 值 |
| 部署工作流未触发 | 未配置 `GH_PAT` | 配置 PAT，或依赖 push 触发备用机制 |
| `npm ci` 失败 | 缺少 `package-lock.json` | 本地先执行 `npm install` 并提交 lock 文件 |
| 数据无变更 | 目标站点无新公告 | 正常现象，跳过提交 |

### 7.3 手动重跑

在 Actions 页面选择失败的工作流运行 → 点击 **Re-run all jobs**，或使用 `workflow_dispatch` 手动触发。

---

## 8. 工作流文件清单

```
.github/workflows/
├── update-data.yml     # 数据采集与提交 (247 行)
└── deploy-pages.yml    # 前端构建与部署 (109 行)
```

---

*文档编号：GD-MPR-CICD-003 v1.0*  
*编制时间：2026 年 6 月 5 日*
