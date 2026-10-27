#!/usr/bin/env python3
"""把框架仓库 output/ 下的研究产物同步成 Starlight 的文档页。

真源是 ../insseek-ai-investment-framework/output/，这里是生成物：
- 每个 .md 复制到 src/content/docs/{资产}/，补 frontmatter（title 取自 H1）
- 去掉 H1（Starlight 用 frontmatter 的 title 当页面标题）
- facts.json 复制到 public/facts/{资产}/，正文里的 data/{日期}/facts.json 改写为可下载链接
- 生成 src/sidebar.generated.mjs，按资产分组，资产内按时间倒序

用法：
    python3 scripts/sync_reports.py            # 同步
    python3 scripts/sync_reports.py --check    # 只检查是否需要同步，退出码 1 表示过期
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT.parent / "insseek-ai-investment-framework" / "output"
DOCS = ROOT / "src" / "content" / "docs"
PUBLIC_FACTS = ROOT / "public" / "facts"
SIDEBAR = ROOT / "src" / "sidebar.generated.mjs"
CONFIG = json.loads((ROOT / "site.config.json").read_text(encoding="utf-8"))

SKIP_DIRS = {".archive", "data", "__pycache__"}
DATA_REF = re.compile(r"data/(\d{8})/facts\.json")


NAMING = ROOT.parent / "insseek-ai-investment-framework" / "docs" / "report-conventions.md"

# 类别是展示层的判断，不是命名表的一部分：命名表说「这是什么产物」，
# 这里说「它该出现在侧边栏的哪一组」。所以映射写在这里，词表来自命名表。
# 入口 → 组 id。组 id 是稳定标识，标题（个股/指数/…）只是展示，
# 改标题不会影响归类；新增一类产物时，改这里 + site.config.json 的 groups 各加一项。
CATEGORY_OF_ENTRY = {
    "invest-index": "index",
    "invest-industry": "industry",
    "invest-bottleneck": "topic",
    "invest-commodity": "commodity",
    "invest-bitcoin": "crypto",
    "invest-portfolio": "portfolio",
}
DEFAULT_CATEGORY = "stock"

# 资产内分五组：先看结论，再看论证，然后是事件、文章、系列
GROUP_OF_TOKEN = {
    "thesis": "结论",
    "research": "研究",
    "team": "研究",
    "management": "研究",
    "screen": "研究",
    "index": "研究",
    "benchmark": "研究",
    "commodity": "研究",
    "bitcoin": "研究",
    "private": "研究",
    "industry": "研究",
    "funnel": "研究",
    "era": "研究",
    "earnings": "财报与事件",
    "news": "财报与事件",
    "checklist": "财报与事件",
    "memo": "财报与事件",
    "income": "财报与事件",
    "latest": "财报与事件",
    "article": "文章",
    "series": "系列",
}
GROUP_ORDER = ["结论", "研究", "财报与事件", "文章", "系列"]


def parse_naming_table() -> tuple[dict, dict]:
    """从框架仓库的命名表读「类型词 → 入口」，让分类跟着命名表走。

    命名表是唯一真源（有 tests/test_mode_naming.py 守着）。这里不另造词表：
    表里新增一个产物类型，同步脚本第二天就知道它叫什么。
    """
    if not NAMING.exists():
        raise SystemExit(f"找不到命名表：{NAMING}")
    row = re.compile(r"^\| (invest-[a-z]+)(?:（[^）]*）)? \| (.+?) \| (.+?) \|$")
    tok = re.compile(r"-([a-z]+)(?:-[a-z]+)*-(?:\{YYYYMMDD\}|\{期间\})|-([a-z]+)\.md")
    token_to_entry = {}
    for line in NAMING.read_text(encoding="utf-8").splitlines():
        m = row.match(line.strip())
        if not m:
            continue
        entry, fmt = m.group(1), m.group(2)
        tokens = {a or b for a, b in tok.findall(fmt)}
        if "team-" in fmt:
            tokens.add("team")
        for token in tokens:
            token_to_entry[token] = entry
    return token_to_entry, set(token_to_entry)


def page_tokens(page: Path, known: set[str]) -> set[str]:
    """页面属于哪类产物：看文件名里的类型词，系列看目录名。"""
    stem = page.stem
    found = {t for t in known if f"-{t}-" in stem or stem.endswith(f"-{t}")}
    parent = page.parent.name
    for token in ("team", "series"):
        if f"{token}-" in parent:
            found.add(token)
    return found


def category_of(tokens: set[str], token_to_entry: dict, name: str) -> str:
    if "对照" in name or "跨资产" in name:
        return "cross"
    for token in ("index", "benchmark", "industry", "funnel", "era", "bottleneck", "commodity", "bitcoin", "private", "latest"):
        if token in tokens:
            entry = token_to_entry.get(token, "")
            return CATEGORY_OF_ENTRY.get(entry, DEFAULT_CATEGORY)
    return DEFAULT_CATEGORY


def group_of(tokens: set[str]) -> str:
    for token in sorted(tokens):
        if token in GROUP_OF_TOKEN:
            return GROUP_OF_TOKEN[token]
    return "研究"


def split_title(text: str, fallback: str) -> tuple[str, str]:
    """取出第一个 H1 当标题，并从正文里删掉它。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            rest = lines[:i] + lines[i + 1 :]
            while rest and not rest[0].strip():
                rest.pop(0)
            return title, "\n".join(rest)
    return fallback, text


def description_of(body: str) -> str:
    """第一段非空、非引用、非表格的文字，截到 80 字。"""
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line[0] in "|>#-*" or line.startswith("```"):
            continue
        plain = re.sub(r"[`*_\[\]()]", "", line)
        return plain[:80]
    return ""


def rewrite_links(body: str, asset: str, depth: int) -> str:
    """facts 用相对路径：页面在 /{slug}/ 下，回退 depth 层就到站点根。

    这样站点挂在根（Netlify）还是子路径（GitHub Pages 项目页）都能点开。
    """
    prefix = "../" * depth
    return DATA_REF.sub(lambda m: f"{prefix}facts/{asset}/{m.group(1)}.json", body)


def target_of(path: Path, source_root: Path) -> Path:
    rel = path.relative_to(source_root)
    return DOCS / rel


def build_page(path: Path, asset: str, depth: int) -> str:
    text = path.read_text(encoding="utf-8")
    title, body = split_title(text, path.stem)
    body = rewrite_links(body, asset, depth)
    # 反引号里的数据包路径变成可点链接，并在页首给一行下载入口
    body = re.sub(r"`((?:\.\./)+facts/[^`]+)`", lambda m: f"[{m.group(1)}]({m.group(1)})", body)
    m = re.search(r"(?:\.\./)+facts/[^\s)\]]+\.json", body)
    if m:
        # 头部固定字段（> 成稿 …）必须在最前面：数据包这行放到整个 > 块之后
        head, rest = [], body.splitlines()
        i = 0
        while i < len(rest) and not rest[i].startswith("> "):
            head.append(rest[i])
            i += 1
        while i < len(rest) and rest[i].startswith("> "):
            head.append(rest[i])
            i += 1
        pack = f"> 数据包：[{m.group(0)}]({m.group(0)})——报告里每个数都能在里面找到出处。"
        body = "\n".join(head) + "\n\n" + pack + "\n\n" + "\n".join(rest[i:]).lstrip("\n")
    front = ["---", f"title: {json.dumps(title, ensure_ascii=False)}"]
    desc = description_of(body)
    if desc:
        front.append(f"description: {json.dumps(desc, ensure_ascii=False)}")
    front.append("---")
    return "\n".join(front) + "\n\n" + body.rstrip() + "\n"


def sync() -> int:
    changed = 0
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)
    if PUBLIC_FACTS.exists():
        shutil.rmtree(PUBLIC_FACTS)
    PUBLIC_FACTS.mkdir(parents=True)
    if not SOURCE.is_dir():
        raise SystemExit(f"找不到产物目录：{SOURCE}")

    token_to_entry, known = parse_naming_table()
    entries = []  # (类别, 资产名或 None, [(组名, [(页面, 标题)])])

    for asset in sorted(p for p in SOURCE.iterdir() if p.is_dir() and p.name not in SKIP_DIRS):
        pages = []
        for md in sorted(asset.rglob("*.md")):
            if any(part in SKIP_DIRS for part in md.parts):
                continue
            if md.name == "README.md" and md.parent.name.startswith(TEAM_PREFIX):
                continue  # 团队分工与仲裁是内部过程记录，不发布
            dest = target_of(md, SOURCE)
            dest.parent.mkdir(parents=True, exist_ok=True)
            rel = md.relative_to(SOURCE).with_suffix("")
            text = build_page(md, asset.name, len(rel.parts))
            dest.write_text(text, encoding="utf-8")
            pages.append((dest, page_title(text, dest.stem)))
            changed += 1
        for facts in sorted(asset.rglob("facts.json")):
            date = facts.parent.name
            dest = PUBLIC_FACTS / asset.name / f"{date}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(facts, dest)
            changed += 1
        if not pages:
            continue
        tokens: set[str] = set()
        for page, _ in pages:
            tokens |= page_tokens(page, known)
        entries.append((category_of(tokens, token_to_entry, asset.name), asset.name,
                        bucketise(pages, known)))

    # 根级产物：行业、专题、组合这类不挂在某个资产目录下
    for md in sorted(SOURCE.glob("*.md")):
        if md.name.startswith("."):
            continue
        rel = md.relative_to(SOURCE).with_suffix("")
        dest = target_of(md, SOURCE)
        text = build_page(md, md.stem, len(rel.parts))
        dest.write_text(text, encoding="utf-8")
        changed += 1
        page = (dest, page_title(text, dest.stem))
        tokens = page_tokens(md, known)
        entries.append((category_of(tokens, token_to_entry, md.stem), None,
                        [(group_of(tokens), [page])]))

    groups = CONFIG.get("groups", [])
    order = [g["id"] for g in groups]
    titles = {g["id"]: g["title"] for g in groups}

    def rank(entry):
        category, asset, _ = entry
        return (order.index(category) if category in order else len(order), asset or "")

    entries.sort(key=rank)

    tree: list[tuple[str, list[tuple[str | None, list]]]] = []
    for category, asset, groups in entries:
        label = titles.get(category, category)
        if not tree or tree[-1][0] != label:
            tree.append((label, []))
        tree[-1][1].append((asset, groups))

    SIDEBAR.write_text(sidebar_module(tree), encoding="utf-8")
    write_index(entries)

    # 对齐检查：产物里出现命名表没有的类型词，说明框架那边加了新产物类型，
    # 而站点还不知道该把它归到哪一组。宁可吵一句，也不要静默归错类。
    unknown = set()
    for page in DOCS.rglob("*.md"):
        for token in re.findall(r"-([a-z]{3,})-", page.stem):
            if token not in known:
                unknown.add(token)
    if unknown:
        print("⚠ 命名表里没有这些类型词，先补 docs/report-conventions.md：" + "、".join(sorted(unknown)))

    # 第二道对齐检查：入口映射出的组 id 必须在 site.config.json 的 groups 里，
    # 否则这一类产物会掉到侧边栏末尾、标题也不对。
    missing = {cat for cat, _, _ in entries if cat not in order}
    if missing:
        print("⚠ site.config.json 的 groups 缺这些 id：" + "、".join(sorted(missing))
              + "（CATEGORY_OF_ENTRY 里新加的组要同步加一项）")
    return changed


def page_title(text: str, fallback: str) -> str:
    m = re.search(r"^title: (.+)$", text, re.M)
    return json.loads(m.group(1)) if m else fallback


KIND = {
    "thesis": "投资结论",
    "research": "研究报告",
    "index": "指数研究",
    "commodity": "商品研究",
    "bitcoin": "比特币研究",
    "memo": "备忘录",
    "checklist": "核查清单",
    "earnings": "财报快评",
    "news": "快评",
    "management": "管理层评估",
    "screen": "筛选结论",
    "industry": "行业研究",
    "benchmark": "基准对比",
    "private": "未上市研究",
    "income": "收息测算",
}

TEAM_PREFIX = "team-"


def page_order(page: Path) -> tuple:
    """组内顺序：投资结论 → 研究 → 多视角 → 视角 → 文章 → 系列。

    同一档内按日期倒序（新的在前），无日期的按文件名升序（视角 01→04）。
    """
    stem = page.stem
    if "-thesis" in stem:
        rank = 0
    elif stem == "最终报告":
        rank = 2
    elif re.match(r"\d+-", stem):
        rank = 4 if TEAM_PREFIX in page.parent.name else 6
    elif "-article-" in stem:
        rank = 5
    else:
        rank = 1
    date = re.search(r"(\d{8})", stem)
    return (rank, -(int(date.group(1)) if date else 0), stem)


def _mmdd(digits: str) -> str:
    return f"{digits[4:6]}-{digits[6:8]}"


def page_date(page: Path) -> str:
    """页面日期，按可信度取：正文头部「成稿」→ 文件名 → 父目录（team-/series-）。

    成稿在前，是因为它对「这份内容是什么时候定稿的」负责；文件名里的日期是发布口径，
    两者不一致时以成稿为准。视角稿与系列稿不是准出产物、没有成稿行，日期来自所在批次目录。
    """
    try:
        head = "\n".join(page.read_text(encoding="utf-8").split("\n")[:20])
    except OSError:
        head = ""
    m = re.search(r"成稿\s*(\d{4})-(\d{2})-(\d{2})", head)
    if m:
        return f"{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{8})", page.stem)
    if m:
        return _mmdd(m.group(1))
    m = re.search(r"(?:team|series)-(\d{8})", page.parent.name)
    return _mmdd(m.group(1)) if m else ""


def page_label(page: Path, title: str) -> str:
    """条目名：只说「这是什么」，日期交给 badge。"""
    stem = page.stem
    for key, name in KIND.items():
        if f"-{key}-" in stem or stem.endswith(f"-{key}"):
            return name
    if stem == "最终报告":
        return "多视角投研报告"
    m = re.match(r"(\d+)-(.+)", stem)
    if m:
        parent = page.parent.name
        prefix = "视角" if TEAM_PREFIX in parent else "系列"
        return f"{prefix} {m.group(1)}：{m.group(2)}"
    return title


def bucketise(pages: list[tuple[Path, str]], known: set[str]):
    """按「结论 / 研究 / 财报与事件 / 文章 / 系列」分组，组内按 page_order 排。"""
    buckets: dict[str, list[tuple[Path, str]]] = {}
    for page, title in pages:
        buckets.setdefault(group_of(page_tokens(page, known)), []).append((page, title))
    ordered = []
    for name in GROUP_ORDER:
        if name in buckets:
            ordered.append((name, sorted(buckets[name], key=lambda item: page_order(item[0]))))
    for name in sorted(buckets):
        if name not in GROUP_ORDER:
            ordered.append((name, sorted(buckets[name], key=lambda item: page_order(item[0]))))
    return ordered


def slug_of(page: Path) -> str:
    return page.relative_to(DOCS).with_suffix("").as_posix().lower()


def badge_of(page: Path) -> str:
    date = page_date(page)
    return f", badge: {{ text: {json.dumps(date)}, variant: 'note' }}" if date else ""


def team_children(pages) -> dict:
    """同目录下的「最终报告 → 0N 视角」从属关系。只有真从属才嵌套，不靠排序猜。"""
    parents = [p for p, _ in pages if p.stem == "最终报告"]
    children: dict = {}
    for parent in parents:
        kids = [(p, t) for p, t in pages
                if p.parent == parent.parent and re.match(r"\d+-", p.stem)]
        if kids:
            children[parent] = kids
    return children


def sidebar_module(tree) -> str:
    """资产下不再分组：页面按类型顺序平铺。

    分组只在「需要跳读」时有用；一个组里只有一页时，组名与页面标题重复一次，
    读者要多点一次才看得到唯一内容。类型靠标题本身表达（结论卡、指数研究、文章、系列 01）。
    """
    def item(page, title, indent):
        return (f"{indent}{{ label: {json.dumps(page_label(page, title), ensure_ascii=False)}, "
                f"slug: {json.dumps(slug_of(page), ensure_ascii=False)}{badge_of(page)} }}")

    lines = ["// 由 scripts/sync_reports.py 生成，不要手改。", "export default ["]
    lines.append("  { label: '关于', link: '/' },")
    for category, items in tree:
        lines.append(f"  {{ label: {json.dumps(category, ensure_ascii=False)}, items: [")
        for asset, groups in items:
            pages = [page for _, in_group in groups for page in in_group]
            if asset is None:
                for page, title in pages:
                    lines.append(item(page, title, "    ") + ",")
                continue
            lines.append(f"    {{ label: {json.dumps(asset, ensure_ascii=False)}, collapsed: true, items: [")
            children = team_children(pages)
            nested = {kid for kids in children.values() for kid, _ in kids}
            for page, title in pages:
                if page in nested:
                    continue
                kids = children.get(page)
                if kids:
                    # Starlight 的侧边栏组不带链接（组只有 label + items），
                    # 所以报告本身作为组内第一项，四个视角跟在后面。
                    lines.append(f"      {{ label: \"多视角投研\", collapsed: false, items: [")
                    lines.append(item(page, title, "        ") + ",")
                    for kid, kid_title in kids:
                        lines.append(item(kid, kid_title, "        ") + ",")
                    lines.append("      ] },")
                else:
                    lines.append(item(page, title, "      ") + ",")
            lines.append("    ] },")
        lines.append("  ] },")
    lines.append("];")
    return "\n".join(lines) + "\n"


def write_index(entries) -> None:
    rows = ["---", "title: 全部报告", "description: 公司、指数、商品与加密资产的价值投资研究。", "---", ""]
    rows.append("按类别与资产整理的研究报告。每份报告都配一个数据包（`facts.json`），")
    rows.append("报告里的每个数字都能在数据包里找到出处，可离线复算。")
    rows.append("")
    rows.append("| 类别 | 资产 | 篇数 | 最近一篇 |")
    rows.append("| --- | --- | --- | --- |")
    for category, asset, groups in entries:
        pages = [page for _, in_group in groups for page in in_group]
        dated = [(m.group(1), title) for page, title in pages if (m := re.search(r"(\d{8})", page.name))]
        latest = max(dated)[1] if dated else pages[0][1]
        rows.append(f"| {category} | {asset or '—'} | {len(pages)} | {latest} |")
    rows.append("")
    (DOCS / "index.md").write_text("\n".join(rows), encoding="utf-8")


def report_missing_dates() -> None:
    """除首页外，每个条目都该有日期；取不到就提醒，不要静默留白。"""
    missing = [p for p in DOCS.rglob("*.md")
               if p.name != "index.md" and not page_date(p)]
    if missing:
        print("⚠ 这些页面取不到日期，badge 会是空的：")
        for p in sorted(missing):
            print("   ", p.relative_to(DOCS))
        print("   日期来源：文件名 YYYYMMDD / 父目录 team-|series-YYYYMMDD / 头部「成稿 YYYY-MM-DD」")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查生成物是否最新")
    args = ap.parse_args()
    if args.check:
        before = snapshot()
        sync()
        after = snapshot()
        if before != after:
            print("生成物已过期，请跑 python3 scripts/sync_reports.py")
            return 1
        print("生成物是最新的")
        return 0
    n = sync()
    print(f"同步完成：{n} 个文件")
    return 0


def snapshot() -> dict[str, str]:
    return {str(p): p.read_text(encoding="utf-8") for p in sorted(DOCS.rglob("*.md"))} if DOCS.exists() else {}


if __name__ == "__main__":
    sys.exit(main())
