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


def asset_groups() -> list[tuple[str, list[Path]]]:
    """按 site.config.json 的 groups 排序资产；配置里没写的资产落到「其他」，按名排序。

    顺序由配置决定，不由 Unicode 码位决定——中文按码位排出来是随机的，
    而读者需要的是稳定的、有意义的顺序。
    """
    if not SOURCE.is_dir():
        raise SystemExit(f"找不到产物目录：{SOURCE}")
    on_disk = {p.name: p for p in SOURCE.iterdir() if p.is_dir() and p.name not in SKIP_DIRS}
    result = []
    for group in CONFIG.get("groups", []):
        assets = [on_disk.pop(name) for name in group["assets"] if name in on_disk]
        if assets:
            result.append((group["title"], assets))
    rest = [on_disk[name] for name in sorted(on_disk)]
    if rest:
        result.append(("其他", rest))
    return result


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
        body = f"> 数据包：[{m.group(0)}]({m.group(0)})——报告里每个数都能在里面找到出处。\n\n" + body
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

    groups = []
    for category, assets in asset_groups():
        for asset in assets:
            pages = []
            for md in sorted(asset.rglob("*.md")):
                if any(part in SKIP_DIRS for part in md.parts):
                    continue
                dest = target_of(md, SOURCE)
                dest.parent.mkdir(parents=True, exist_ok=True)
                # 页面 URL 是 /{资产}/.../{文件名}/，深度按相对 output/ 的路径算
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
            if pages:
                groups.append((category, asset.name, pages))

    nested: list[tuple[str, list[tuple[str, list]]]] = []
    for category, asset_name, pages in groups:
        if not nested or nested[-1][0] != category:
            nested.append((category, []))
        nested[-1][1].append((asset_name, pages))

    SIDEBAR.write_text(sidebar_module(nested), encoding="utf-8")
    write_index(groups)
    return changed


def page_title(text: str, fallback: str) -> str:
    m = re.search(r"^title: (.+)$", text, re.M)
    return json.loads(m.group(1)) if m else fallback


KIND = {
    "thesis": "结论卡",
    "research": "研究报告",
    "article": "文章",
    "index": "指数研究",
    "commodity": "商品研究",
    "bitcoin": "比特币研究",
    "memo": "备忘录",
    "checklist": "核查清单",
    "earnings": "财报快评",
    "news": "快评",
    "management": "管理层评估",
    "screen": "筛选结论",
}


TEAM_PREFIX = "team-"
SERIES_PREFIX = "series-"


def page_order(page: Path) -> tuple:
    """组内顺序：结论卡、研究报告、团队合成、分工、视角、文章、系列。

    早先按文件名倒序，结论卡因为字母 t 排在 research 前面，纯属巧合；
    这里把「先看结论、再看论证」写成显式规则。
    """
    stem = page.stem
    if "-thesis" in stem:
        rank = 0
    elif stem == "最终报告":
        rank = 2
    elif stem == "README":
        rank = 3
    elif re.match(r"\d+-", stem):
        rank = 4 if TEAM_PREFIX in page.parent.name else 6
    elif "-article-" in stem:
        rank = 5
    else:
        rank = 1
    date = re.search(r"(\d{8})", stem)
    return (rank, "" if date is None else "0" if False else date.group(1), stem)


def page_label(page: Path, title: str) -> str:
    stem = page.stem
    date = re.search(r"(\d{8})", stem)
    tail = date.group(1) if date else ""
    for key, name in KIND.items():
        if f"-{key}" in stem:
            return f"{name} {tail}".strip() if key != "thesis" else name
    if stem == "最终报告":
        return "团队合成报告"
    if stem == "README":
        return "团队分工与仲裁"
    m = re.match(r"(\d+)-(.+)", stem)
    if m:
        parent = page.parent.name
        prefix = "视角" if "team-" in parent else "系列"
        return f"{prefix} {m.group(1)}：{m.group(2)}"
    return title


def sidebar_module(groups: list[tuple[str, list[tuple[str, list[Path]]]]]) -> str:
    lines = ["// 由 scripts/sync_reports.py 生成，不要手改。", "export default ["]
    lines.append("  { label: '关于', link: '/' },")
    for category, assets in groups:
        lines.append(f"  {{ label: {json.dumps(category, ensure_ascii=False)}, items: [")
        for name, pages in assets:
            lines.append(f"    {{ label: {json.dumps(name, ensure_ascii=False)}, items: [")
            for page, title in sorted(pages, key=lambda item: page_order(item[0])):
                slug = page.relative_to(DOCS).with_suffix("").as_posix().lower()
                label = page_label(page, title)
                lines.append(
                    f"      {{ label: {json.dumps(label, ensure_ascii=False)}, "
                    f"slug: {json.dumps(slug, ensure_ascii=False)} }},"
                )
            lines.append("    ] },")
        lines.append("  ] },")
    lines.append("];")
    return "\n".join(lines) + "\n"



def write_index(groups: list[tuple[str, list[Path]]]) -> None:
    rows = ["---", "title: 全部报告", "description: 公司、指数、商品与加密资产的价值投资研究。", "---", ""]
    rows.append("按资产分类的研究报告。每份报告都配一个数据包（`facts.json`），")
    rows.append("报告里的每个数字都能在数据包里找到出处，可离线复算。")
    rows.append("")
    rows.append("| 类别 | 资产 | 篇数 | 最近一篇 |")
    rows.append("| --- | --- | --- | --- |")
    for category, name, pages in groups:
        dated = [(re.search(r"(\d{8})", page.name), title) for page, title in pages]
        dated = [(m.group(1), title) for m, title in dated if m]
        latest = max(dated)[1] if dated else pages[0][1]
        rows.append(f"| {category} | {name} | {len(pages)} | {latest} |")
    rows.append("")
    (DOCS / "index.md").write_text("\n".join(rows), encoding="utf-8")


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
