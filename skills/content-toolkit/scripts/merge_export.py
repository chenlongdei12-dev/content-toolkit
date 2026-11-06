#!/usr/bin/env python3
"""文案和数据合并：Get笔记逐字稿 + 社媒助手数据 → 带数据 frontmatter 的 md + INDEX

用法：
  python3 merge_export.py --transcripts-dir <biji导出目录> --stats <social_stats.py输出的.json> \
      [-o 输出目录] [--pretty]

- 逐字稿目录：biji_export.py export 产出的 {博主名}_{follow_id}/，文件名 {序号}_{post_id}_{标题}.md
- 匹配策略（2026-11-06 升级）：**① 抖音视频ID精确匹配**（逐字稿 md 里的 douyin/iesdouyin 链接 ↔ 数据表视频链接；同视频多稿共享同一行数据）→ ② 标题归一化精确 → ③ difflib 相似度 ≥0.75 → ④ 包含关系；都不中算未匹配（如实报告）
- 输出：<输出目录>/merged/ 下同名 md（YAML frontmatter 数据 + 原正文）+ INDEX.md 总表
"""
import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def normalize_title(t):
    """归一化标题：去空白/表情/#话题/标点，小写。"""
    t = (t or "").lower()
    t = re.sub(r"#[^#\s]{1,30}", "", t)          # 话题标签
    t = re.sub(r"[\W_]+", "", t, flags=re.UNICODE)  # 标点/空白/下划线
    return t


def extract_video_id(text):
    """从文本里抽抖音视频ID（douyin.com/.../video/123... 或 iesdouyin share 链接）。"""
    m = re.search(r"(?:iesdouyin|douyin)\.com/(?:\S*?/)?video/(\d{15,})", text or "")
    return m.group(1) if m else None


def load_transcripts(tdir):
    """解析 biji 导出目录 → [{file, seq, post_id, title, publish_time, text}]"""
    out = []
    for f in sorted(Path(tdir).glob("*.md")):
        m = re.match(r"^(\d+)_(\d+)_(.*)\.md$", f.name)
        seq, pid, title = (int(m.group(1)), m.group(2), m.group(3)) if m else (None, None, f.stem)
        text = f.read_text(encoding="utf-8")
        h = re.match(r"^#\s+(.+)$", text, re.M)
        if h:
            title = h.group(1).strip()
        pub = None
        pm = re.search(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2}[\d :]*)", text)
        if pm:
            pub = pm.group(1).strip()
        out.append({"file": f, "seq": seq, "post_id": pid, "title": title,
                    "publish_time": pub, "text": text, "video_id": extract_video_id(text)})
    return out


def match_stats(transcripts, stats_items):
    """给每篇逐字稿匹配一条社媒数据。返回 (results, unmatched_stats_idx)。
    results 每项: (transcript, stats_item_or_None, score, via) via∈{link,title,None}
    策略：链接视频ID精确匹配（同视频多稿共享）→ 标题兜底（跳过已链接匹配的行防抢错）。"""
    used = set()
    results = [None] * len(transcripts)

    vid_map = {}
    for i, s in enumerate(stats_items):
        vid = extract_video_id(s.get("link") or "")
        if vid and vid not in vid_map:
            vid_map[vid] = i
    for idx, t in enumerate(transcripts):
        i = vid_map.get(t.get("video_id") or "")
        if i is not None:
            used.add(i)
            results[idx] = (t, stats_items[i], 1.0, "link")

    for idx, t in enumerate(transcripts):
        if results[idx] is not None:
            continue
        nt = normalize_title(t["title"])
        best, best_score, best_i = None, 0.0, None
        for i, s in enumerate(stats_items):
            if i in used:
                continue
            ns = normalize_title(s.get("title"))
            if not ns or not nt:
                continue
            if nt == ns:
                best, best_score, best_i = s, 1.0, i
                break
            if nt in ns or ns in nt:
                score = min(len(nt), len(ns)) / max(len(nt), len(ns))
            else:
                score = difflib.SequenceMatcher(None, nt, ns).ratio()
            if score > best_score:
                best, best_score, best_i = s, score, i
        if best_score >= 0.75:
            used.add(best_i)
            results[idx] = (t, best, best_score, "title")
        else:
            results[idx] = (t, None, best_score, None)

    unmatched = [i for i in range(len(stats_items)) if i not in used]
    return results, unmatched


def yaml_str(v):
    return "null" if v is None else json.dumps(str(v), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description="合并逐字稿与社媒数据")
    ap.add_argument("--transcripts-dir", required=True, help="biji 导出目录")
    ap.add_argument("--stats", required=True, help="social_stats.py 输出的 JSON")
    ap.add_argument("-o", "--output", help="输出目录（默认 transcripts-dir 同级的 merged/）")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    tdir = Path(args.transcripts_dir).expanduser()
    stats = json.loads(Path(args.stats).expanduser().read_text(encoding="utf-8"))
    stats_items = stats.get("items", [])

    transcripts = load_transcripts(tdir)
    if not transcripts:
        raise SystemExit(f"[错误] {tdir} 里没有逐字稿 md")

    out_dir = Path(args.output).expanduser() if args.output else tdir.parent / "merged" / tdir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    results, unmatched_idx = match_stats(transcripts, stats_items)
    matched = sum(1 for _, s, _, _ in results if s)
    via_link = sum(1 for _, s, _, v in results if s and v == "link")
    via_title = matched - via_link

    rows = []
    for t, s, score, via in results:
        stats_d = (s or {}).get("stats") or {}
        link = (s or {}).get("link") or ""
        author = (s or {}).get("author") or ""
        pub = t.get("publish_time") or (s or {}).get("publish_time") or ""
        fname = t["file"].name
        fm = ["---",
              f"post_id: {yaml_str(t['post_id'])}",
              f"title: {yaml_str(t['title'])}",
              f"publish_time: {yaml_str(pub)}",
              f"author: {yaml_str(author)}",
              f"link: {yaml_str(link)}",
              f"stats_time: {yaml_str(stats.get('source_file'))}",
              "stats:"]
        for k in ("likes", "comments", "collects", "shares", "views"):
            fm.append(f"  {k}: {stats_d.get(k, 'null')}")
        fm += [f"match_score: {round(score, 2) if s else 0}",
               f"match_via: {yaml_str(via)}",
               f"merged_at: {yaml_str(time.strftime('%Y-%m-%d %H:%M:%S'))}",
               "---"]
        body = re.sub(r"^---\n.*?\n---\n?", "", t["text"], flags=re.S)  # 去旧 frontmatter
        (out_dir / fname).write_text("\n".join(fm) + "\n" + body.strip() + "\n", encoding="utf-8")
        rows.append({"title": t["title"], "publish_time": pub, "stats": stats_d,
                     "file": fname, "matched": bool(s), "link": link})

    rows.sort(key=lambda r: (r["publish_time"] or "", r["file"]), reverse=True)
    lines = ["# 导出合并索引", "",
             f"- 逐字稿：{tdir}", f"- 数据源：{stats.get('source_file')}",
             f"- 匹配：{matched}/{len(transcripts)}（链接 {via_link} / 标题 {via_title}），数据行未用：{len(unmatched_idx)}", "",
             "| 发布时间 | 标题 | 点赞 | 评论 | 收藏 | 转发 | 匹配 | 文件 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        st = r["stats"]
        title = r["title"].replace("|", "\\|")
        lines.append(f"| {r['publish_time'] or ''} | {title} "
                     f"| {st.get('likes', '-')} | {st.get('comments', '-')} "
                     f"| {st.get('collects', '-')} | {st.get('shares', '-')} "
                     f"| {'✅' if r['matched'] else '❌'} | {r['file']} |")
    if unmatched_idx:
        lines += ["", "## 数据表里没匹配上的行", ""]
        for i in unmatched_idx:
            it = stats_items[i]
            lines.append(f"- {it.get('publish_time') or ''} {it.get('title')}")
    (out_dir / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"ok": True, "transcripts": len(transcripts), "stats_rows": len(stats_items),
                      "matched": matched, "via_link": via_link, "via_title": via_title,
                      "unmatched_stats": len(unmatched_idx),
                      "output_dir": str(out_dir), "index": str(out_dir / "INDEX.md")},
                     ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
