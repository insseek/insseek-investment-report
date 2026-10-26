# 里探投资报告

把 `../insseek-ai-investment-framework/output/` 里的研究产物发布成静态站。

内容全部来自框架仓库；这个仓库只负责渲染、搜索与部署。

## 技术栈

- **Astro + Starlight**：构建期生成静态 HTML，搜索引擎与分享卡片能拿到正文
- **Pagefind**：构建时建索引，中文按字切分，开箱可用
- **纯 Markdown**：报告不依赖主题的扩展语法，将来换框架只换渲染层

运行环境：**Node 24**（Astro 7 要求 ≥ 22.23.4，22 的早期次版本会直接构建失败）。

## 命令

```bash
npm install         # 首次
npm run dev         # 本地预览，http://localhost:4321
npm run build       # 同步产物 + 构建到 dist/
npm run check       # 检查生成物是否最新（CI 用）
```

构建产物 `dist/` 是纯静态文件，扔到 GitHub Pages、Cloudflare Pages 或任何静态服务器都能跑。

## 内容从哪来

真源是框架仓库的 `output/`：

```
insseek-ai-investment-framework/output/{资产}/
├── {资产}-research-{YYYYMMDD}.md   研究报告
├── {资产}-thesis.md                结论卡
├── {资产}-article-{YYYYMMDD}.md    对外文章
├── articles/series-{YYYYMMDD}/     系列子篇
├── team-{YYYYMMDD}/                团队模式：视角稿 + 合成
└── data/{YYYYMMDD}/facts.json      数据包
```

`scripts/sync_reports.py` 做四件事：

1. 复制 Markdown 到 `src/content/docs/`，用 H1 生成 frontmatter 的 `title`
2. 去掉正文里的 H1（Starlight 用 frontmatter 渲染标题，留着会重复）
3. 把 `data/{日期}/facts.json` 改写成**相对路径**（按页面深度回退，如 `../../facts/小米/20261026.json`）
   并在页首加一行下载链接。相对路径的好处：站点挂在域名根（Netlify）还是子路径（Pages 项目页）都能点开
4. 生成 `src/sidebar.generated.mjs`（按资产分组，资产内按日期倒序）

所以：**改内容去框架仓库改，改样式在这里改。** 手改 `src/content/docs/` 会被下次同步覆盖。

## 目录

```
astro.config.mjs          站点配置（标题、语言、侧边栏）
src/content.config.ts     内容集合定义
src/content/docs/         生成物：每个 md 一页
src/sidebar.generated.mjs 生成物：侧边栏
public/facts/             生成物：数据包副本
scripts/sync_reports.py   同步脚本
```

## 发布（全在本地完成）

`output/` 不进 git，所以这条链没有服务端取数环节——内容在本地生成好，再提交发布：

```bash
# 1. 在框架仓库把报告与数据包改完（output/ 只在本地）
# 2. 把本地产物搬进站点
npm run sync
# 3. 本地构建验证
npm run build
# 4. 提交并推送：提交的是生成好的页面与数据包副本
git add -A && git commit -m "同步报告" && git push
```

推上去之后，站点仓库自带全部 Markdown 与 `public/facts/`，GitHub Pages 只需要跑 `astro build`（可选：用官方 Astro Action），不依赖框架仓库。

也就是说：**框架仓库管研究与数据，站点仓库管发布**。前者不进 git 的产物，由后者落地成可部署的页面。

## 部署一：GitHub Pages（主站）

**一次性设置**（已做过，换仓库时照抄）：

1. 仓库 Settings → Pages → Build and deployment → Source 选 **GitHub Actions**
2. 下面的两张建议卡片（GitHub Pages Jekyll / Static HTML）**不要点 Configure**——那是给“仓库里没有工作流”的项目准备的模板，点了会多出一个工作流，与我们的抢着往 Pages 发布
3. 工作流权限不用改，`.github/workflows/deploy.yml` 里已声明 `pages: write` 与 `id-token: write`

**工作流做什么**：

| 部分 | 内容 | 作用 |
|---|---|---|
| `on` | `push: branches: [main]` + `workflow_dispatch` | 推 main 自动发；也能在 Actions 页面点 Run workflow |
| `permissions` | `contents: read`、`pages: write`、`id-token: write` | 缺 `pages: write` 会在 deploy 那步 403 |
| `concurrency` | `group: pages`、`cancel-in-progress: true` | 连推两次时只跑新的 |
| build | checkout → setup-node **24** → `npm ci` → `npm run build:ci` → configure-pages → upload-pages-artifact(`dist`) | 生成并上传 `dist/` |
| deploy | `needs: build` → `deploy-pages@v4` | 发布，`page_url` 即站点地址 |

**为什么用 `build:ci` 而不是 `build`**：`build` 会先跑同步脚本，而同步需要本地框架仓库的 `output/`，CI 上没有。生成好的页面与 `public/facts/` 已经提交在仓库里，CI 只做 `astro build`。

**为什么 Node 写死 24**：Astro 7 要求 ≥ 22.23.4；`node-version: 22` 会装到更早的次版本，构建直接失败。

**`configure-pages` 报 `Get Pages site failed`**：Pages 还没开。试过让它自己建（`enablement: true`），`GITHUB_TOKEN` 没有创建 Pages 的权限，只能手工在设置里选 Source。

站点地址：`https://insseek.github.io/insseek-investment-report/`。子路径来自 `site.config.json` 的 `base`，不要去改工作流。

## 部署二：Netlify（备用/镜像，可选）

同一份代码，只多一个环境变量：

| 字段 | 填什么 |
|---|---|
| Branch to deploy | `main` |
| Base directory | 留空 |
| Build command | `npm run build:ci` |
| Publish directory | `dist` |
| Functions directory | 留空 |
| `BASE` | `/` |
| `NODE_VERSION` | `24` |

`BASE=/` 是关键：Netlify 挂在域名根，而默认 `base` 是 `/insseek-investment-report`，不改的话 CSS 与 JS 会 404，页面出来是白底黑字没有样式。

内容来自同一批文件，两个平台可以并存；页内的数据包链接是相对路径，两边都不用额外配置。

## 常见问题

- `npm` 报 `~/.npm` 权限错误：本机缓存目录属主不对，加 `--cache /tmp/npmcache` 即可。
- `astro` 报 `EPERM: mkdir ~/.astro`：设 `ASTRO_TELEMETRY_DISABLED=1 XDG_CONFIG_HOME=/tmp/xdgconfig`。
- 页面里出现旧数字：先去框架仓库改报告与数据包，再 `npm run sync`；不要手改 `src/content/docs/`。
- 页面能开但没样式、白底黑字：`base` 与部署路径不匹配。Pages 子路径用 `site.config.json` 里的值；Netlify 根目录设 `BASE=/`。
- Actions 报 `Get Pages site failed`：Settings → Pages 的 Source 没选 GitHub Actions。
- Actions 在 `npm run build:ci` 处失败并提到 Node 版本：工作流的 `node-version` 不是 24。
- 首页标题出现两次「里探投资报告」：Starlight 会把站点名拼在页面标题后，首页标题与站点名同名时重复；改首页 frontmatter 的 `title` 即可。

## 免责声明

所有内容为个人研究记录，不构成投资建议。数据以原文为准，过期数据以数据包的 `meta.as_of` 为准。
