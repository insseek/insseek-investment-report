# 里探投资报告

把 `../insseek-ai-investment-framework/output/` 里的研究产物发布成静态站。

内容全部来自框架仓库；这个仓库只负责渲染、搜索与部署。

## 技术栈

- **Astro + Starlight**：构建期生成静态 HTML，搜索引擎与分享卡片能拿到正文
- **Pagefind**：构建时建索引，中文按字切分，开箱可用
- **纯 Markdown**：报告不依赖主题的扩展语法，将来换框架只换渲染层

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
3. 把 `data/{日期}/facts.json` 改写成 `/facts/{资产}/{日期}.json` 并在页首加下载链接
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

## 常见问题

- `npm` 报 `~/.npm` 权限错误：本机缓存目录属主不对，加 `--cache /tmp/npmcache` 即可。
- `astro` 报 `EPERM: mkdir ~/.astro`：设 `ASTRO_TELEMETRY_DISABLED=1 XDG_CONFIG_HOME=/tmp/xdgconfig`。
- 页面里出现旧数字：先去框架仓库改报告与数据包，再 `npm run sync`；不要手改 `src/content/docs/`。

## 免责声明

所有内容为个人研究记录，不构成投资建议。数据以原文为准，过期数据以数据包的 `meta.as_of` 为准。
