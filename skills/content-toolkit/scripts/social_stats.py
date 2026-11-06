#!/usr/bin/env python3
"""社媒助手导出数据解析：xlsx/csv → 统一 JSON（供 merge_export.py 合并）

用法：
  python3 social_stats.py <社媒助手导出的.xlsx或.csv> [-o 输出.json] [--pretty]

- xlsx 用纯标准库解析（zipfile+xml），无需 openpyxl
- csv 自动尝试 UTF-8(BOM)/GBK 编码
- 列名自动识别（标题/发布时间/点赞/评论/收藏/转发/链接 的常见叫法）
- 识别不了的列会在输出的 unmatched_columns 里列出，方便校准
"""
import argparse
import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# 列名候选：按常见度排序
COLUMN_CANDIDATES = {
    "title": ["标题", "笔记标题", "视频标题", "作品标题", "文案", "简介", "内容", "描述", "视频描述", "视频简介", "笔记描述", "标题/简介"],
    "publish_time": ["发布时间", "发布日期", "发布日期时间", "创建时间", "时间", "日期"],
    "likes": ["点赞", "点赞数", "点赞量", "获赞", "赞"],
    "comments": ["评论", "评论数", "评论量", "留言数"],
    "collects": ["收藏", "收藏数", "收藏量"],
    "shares": ["转发", "分享", "转发数", "分享数", "转发量", "分享量"],
    "link": ["链接", "视频链接", "作品链接", "地址", "详情链接"],
    "author": ["作者", "博主", "昵称", "账号", "达人昵称", "达人名称"],
    "views": ["播放", "播放量", "浏览量", "观看"],
}


def read_xlsx(path):
    """纯标准库读 xlsx：第一个 sheet → [[cell,...], ...]（字符串值）。"""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(
                    "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
        # 找第一个 sheet 的 xml（优先 workbook.xml 里的顺序，简化：sheet1.xml 或按关系）
        names = z.namelist()
        sheet_name = None
        for cand in ("xl/worksheets/sheet1.xml",):
            if cand in names:
                sheet_name = cand
                break
        if sheet_name is None:
            sheets = [n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml", n)]
            if not sheets:
                raise ValueError("xlsx 里没有 worksheet")
            sheet_name = sorted(sheets)[0]
        root = ET.fromstring(z.read(sheet_name))
        rows = []
        for row in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
            cells = {}
            for c in row.findall("m:c", NS):
                ref = c.get("r", "")
                col = re.match(r"([A-Z]+)", ref)
                idx = 0
                if col:
                    for ch in col.group(1):
                        idx = idx * 26 + (ord(ch) - 64) - 1
                v = c.find("m:v", NS)
                is_node = c.find("m:is", NS)
                if is_node is not None:
                    val = "".join(t.text or "" for t in is_node.iter(
                        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
                elif v is None:
                    val = ""
                elif c.get("t") == "s":
                    val = shared[int(v.text)]
                else:
                    val = v.text or ""
                cells[idx] = (val or "").strip()
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(i, "") for i in range(width)])
        return rows


def read_csv(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("无法识别 CSV 编码（试过 utf-8/gb18030）")
    # 去掉可能的逗号分隔符行（分隔符行如 ----）
    lines = [ln for ln in text.splitlines() if not re.match(r"^-{3,}", ln.strip())]
    return [row for row in csv.reader(io.StringIO("\n".join(lines)))]


def detect_header(rows):
    """找到表头行：含 ≥2 个候选列名的第一行。返回 (header_idx, colmap)。"""
    for i, row in enumerate(rows[:10]):  # 表头一般在前 10 行
        colmap, hits = {}, 0
        for j, cell in enumerate(row):
            c = str(cell).strip().replace(" ", "")
            for field, cands in COLUMN_CANDIDATES.items():
                if field not in colmap and any(c == x.replace(" ", "") or c.startswith(x) for x in cands):
                    colmap[field] = j
                    hits += 1
        if hits >= 2:
            return i, colmap
    return None, {}


def parse_number(v):
    """'1.2万' → 12000；'1,234' → 1234；'' → None。"""
    if v is None or v == "":
        return None
    s = str(v).replace(",", "").strip()
    m = re.match(r"^([\d.]+)\s*万$", s)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.match(r"^([\d.]+)\s*w$", s, re.I)
    if m:
        return int(float(m.group(1)) * 10000)
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description="社媒助手导出数据 → 统一 JSON")
    ap.add_argument("file", help="社媒助手导出的 .xlsx / .csv")
    ap.add_argument("-o", "--output", help="输出 JSON 路径（默认打印到终端）")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    rows = read_xlsx(path) if path.suffix.lower() == ".xlsx" else read_csv(path)
    if not rows:
        raise SystemExit("[错误] 表格是空的")

    hidx, colmap = detect_header(rows)
    if hidx is None:
        raise SystemExit("[错误] 没识别到表头（需要至少包含 标题/点赞/评论 等列名）。"
                         "请打开文件确认列名后在此脚本 COLUMN_CANDIDATES 里补充。")
    used = set(colmap.values())
    unmatched = [str(rows[hidx][j]) for j in range(len(rows[hidx])) if j not in used and str(rows[hidx][j]).strip()]

    items = []
    for row in rows[hidx + 1:]:
        def cell(field):
            j = colmap.get(field)
            return str(row[j]).strip() if j is not None and j < len(row) else ""
        title = cell("title")
        if not title or re.fullmatch(r"[\d./-]+", title):  # 跳过汇总行/日期行
            continue
        item = {"title": title}
        if cell("publish_time"):
            item["publish_time"] = cell("publish_time")
        if cell("link"):
            item["link"] = cell("link")
        if cell("author"):
            item["author"] = cell("author")
        stats = {}
        for k in ("likes", "comments", "collects", "shares", "views"):
            n = parse_number(cell(k))
            if n is not None:
                stats[k] = n
        if stats:
            item["stats"] = stats
        items.append(item)

    out = {"ok": True, "source_file": str(path), "count": len(items),
           "columns_detected": {k: str(rows[hidx][v]) for k, v in colmap.items()},
           "unmatched_columns": unmatched, "items": items}
    text = json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
        print(json.dumps({"ok": True, "count": len(items), "output": args.output,
                          "columns": out["columns_detected"]}, ensure_ascii=False))
    else:
        print(text)


if __name__ == "__main__":
    main()
