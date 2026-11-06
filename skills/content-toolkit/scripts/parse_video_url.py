#!/usr/bin/env python3
"""步骤2：视频链接 → 觖频文件直链（去水印解析）

规则：
  - share_url/page_url 已是音视频直链（.mp4 等）→ 直接采用，跳过去水印（用户约定）
  - Monid 已给 video_file_url → 跳过
  - 否则调用 config.json 中 parser 配置的第三方解析接口
  - 解析接口返回结构未知时：先按 video_url_paths 取，取不到就递归扫描响应里的直链

产出：videos.json 中各条目的 video_file_url 填好，stage → parsed。
注意：抖音 CDN 直链通常有时效（几小时），解析完尽快跑步骤3转写。
"""
import argparse
import sys
import time
from pathlib import Path
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DEFAULT_FIELD_MAP, deep_get, first_value, http_json,
                    is_direct_media_url, monid_run, now_str, normalize_time,
                    scan_media_urls, store_load, store_save, load_config)


def parse_one(cfg, share_url):
    """解析直链。mode=auto（默认）：Monid douyin.video 优先，失败切第三方 url_template 兜底。
    返回 (media_url, 来源标记, extra_data)；extra_data 是视频详情 dict 时用于回填。"""
    p = cfg.get("parser", {})
    m = cfg.get("monid", {})
    mode = p.get("mode") or "auto"

    # 一级：Monid 网关 douyin.video（含数据回填）
    if mode in ("auto", "monid") and m.get("enabled") and m.get("token"):
        try:
            run = monid_run(cfg, p.get("provider", "anyapi"),
                            p.get("video_endpoint", "/douyin.video"), {"url": share_url})
            data = deep_get(run, "output.data") or {}
            media = data.get("videoUrl")
            if isinstance(media, str) and media.startswith("http"):
                return media, "monid", data
        except Exception as e:
            print(f"    （Monid 解析未成：{e}；尝试兜底接口）")
    if mode == "monid":
        return None, "no_media_found", None

    # 二级：第三方去水印接口（zhuceka 等），{url} 替换为编码后的链接
    if p.get("url_template"):
        url = p["url_template"].replace("{url}", urllib.parse.quote(share_url, safe=""))
        resp = http_json(p.get("method", "GET").upper(), url,
                         headers=dict(p.get("headers", {})), body=p.get("body"))
        for path in p.get("video_url_paths", []):
            v = deep_get(resp, path)
            if isinstance(v, str) and v.startswith("http"):
                return v, "http", (resp.get("data") if isinstance(resp, dict) else None)
        found = scan_media_urls(resp, limit=3)
        if found:
            return found[0], "http_scan", None
        return resp, "no_media_found", None
    return None, "not_configured", None


def backfill(v, data, field_map):
    """解析接口返回的视频详情：回填缺失的标题/作者/数据（增量更新 stats）。"""
    if not isinstance(data, dict):
        return
    for key in ("title", "author_name", "author_id", "publish_time"):
        cand = first_value(data, field_map.get(key) or [])
        if cand and not v.get(key):
            v[key] = normalize_time(cand) if key == "publish_time" else cand
    stats = v.setdefault("stats", {})
    changed = False
    for k in ("likes", "comments", "shares", "collects"):
        cand = first_value(data, field_map.get(k) or [])
        if cand is not None:
            try:
                cand = int(cand)
            except (TypeError, ValueError):
                continue
            if stats.get(k) != cand:
                stats[k] = cand
                changed = True
    if changed:
        v["stats_time"] = now_str()


def main():
    ap = argparse.ArgumentParser(description="解析视频文件直链")
    ap.add_argument("--config", help="指定 config.json 路径")
    ap.add_argument("--video-id", help="只处理指定 video_id（可选）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    store = store_load(cfg)
    vids = store["videos"]

    targets = [v for v in vids.values()
               if (not args.video_id or v.get("video_id") == args.video_id)
               and not v.get("video_file_url")
               and (v.get("share_url") or v.get("page_url"))]
    if not targets:
        print("[完成] 没有待解析的条目（全部已有直链或缺少链接）。")
        return

    ok = fail = skip = 0
    for v in targets:
        vid = v["video_id"]
        url = v.get("share_url") or v.get("page_url")
        if is_direct_media_url(url):
            v["video_file_url"] = url
            v["video_file_source"] = "direct"
            v["stage"] = "parsed"
            skip += 1
            print(f"  [跳过解析·已是直链] {vid}")
            continue
        try:
            media, status, extra = parse_one(cfg, url)
            if status in ("monid", "http", "http_scan"):
                v["video_file_url"] = media
                v["video_file_source"] = f"parser:{status}"
                v["parsed_at"] = now_str()
                v["stage"] = "parsed"
                if extra is not None:
                    backfill(v, extra, cfg.get("monid", {}).get("field_map") or DEFAULT_FIELD_MAP)
                ok += 1
                print(f"  [解析成功] {vid} ← {status}")
            elif status == "not_configured":
                print("[跳过] parser 未配置且 monid 未启用：请在 config.json 的 monid 段填 token 并 enabled=true（走 Monid 去水印），或在 parser.url_template 填第三方接口。")
                break
            else:
                v["parse_error"] = str(media)[:300]
                fail += 1
                print(f"  [解析失败] {vid}：响应里没有音视频直链，已把响应存入 parse_error 字段")
        except Exception as e:
            v["parse_error"] = str(e)[:300]
            fail += 1
            print(f"  [解析出错] {vid}：{e}")
        time.sleep(0.8)  # 控制频率（Monid/解析接口可承受）

    store_save(cfg, store)
    print(f"[完成] 直链跳过 {skip} / 解析成功 {ok} / 失败 {fail}。提醒：直链有时效，尽快执行步骤3转写。")


if __name__ == "__main__":
    main()
