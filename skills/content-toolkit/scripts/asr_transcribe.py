#!/usr/bin/env python3
"""步骤3：视频直链 → 阿里云百炼 Paraformer 录音文件转写 → 逐字稿

- 输入：videos.json 中有 video_file_url 且未转写的条目（mp4 视频文件可直接提交，无需提取音频）
- 提交异步任务（X-DashScope-Async）→ 轮询 → 下载结果 JSON（结果链接 24 小时有效，即时落盘）
- 产出：workspace/transcripts/<video_id>.md（逐字稿）+ .raw_asr/<video_id>.json（原始分句/时间戳）
- 可重复执行：task_id 持久化在 videos.json，中断后重跑会接着轮询，不会重复提交计费

鉴权：百炼 DashScope API Key（sk- 开头，百炼控制台创建），填在 config.json 的
dashscope.api_key 或环境变量 DASHSCOPE_API_KEY。注意：不是阿里云 RAM AccessKey。
文档：https://help.aliyun.com/zh/model-studio/paraformer-recorded-speech-recognition-restful-api
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (HttpError, deep_get, extract_video_id, http_download, http_json,
                    now_str, store_load, store_save, load_config)
import re

ERROR_HINTS = {
    "InvalidFile.DownloadFailed": "阿里云下载不了该直链（可能有防盗链/已过期）。换一个解析接口重新拿直链，或下载到本地后手动走通义听悟。",
    "InvalidApiKey": "API Key 无效：确认填的是百炼 DashScope 的 sk- 开头 Key，且已开通模型服务。",
    "Throttling": "触发限流，稍后重跑本脚本即可（task_id 已保存，会续着轮询）。",
    "SUCCESS_WITH_NO_VALID_FRAGMENT": "文件下载成功但没识别到有效语音：该视频大概率是纯音乐/BGM 无人声，属正常现象，跳过即可。",
}


def submit(cfg, key, media_url):
    d = cfg.get("dashscope", {})
    base = d.get("base_url", "https://dashscope.aliyuncs.com").rstrip("/")
    body = {
        "model": d.get("model", "paraformer-v2"),
        "input": {"file_urls": [media_url]},
        "parameters": {
            "channel_id": [0],
            "language_hints": d.get("language_hints", ["zh", "en"]),
        },
    }
    resp = http_json("POST", base + "/api/v1/services/audio/asr/transcription",
                     headers={"Authorization": f"Bearer {key}", "X-DashScope-Async": "enable"},
                     body=body)
    task_id = deep_get(resp, "output.task_id")
    if not task_id:
        raise HttpError(f"提交失败：{json.dumps(resp, ensure_ascii=False)[:300]}")
    return task_id


def query(cfg, key, task_id):
    base = cfg.get("dashscope", {}).get("base_url", "https://dashscope.aliyuncs.com").rstrip("/")
    return http_json("POST", f"{base}/api/v1/tasks/{task_id}",
                     headers={"Authorization": f"Bearer {key}"})


def save_result(cfg, v, result_json):
    vid = v["video_id"]
    ws = Path(cfg["workspace"])
    raw_dir = ws / ".raw_asr"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{vid}.json").write_text(
        json.dumps(result_json, ensure_ascii=False, indent=2), encoding="utf-8")

    text = ""
    duration = None
    try:
        tr = result_json["transcripts"][0]
        text = tr.get("text", "") or "".join(s.get("text", "") for s in tr.get("sentences", []))
        duration = round(deep_get(result_json, "properties.original_duration_in_milliseconds") / 1000, 1)
    except (KeyError, IndexError, TypeError):
        pass

    t_dir = ws / "transcripts"
    t_dir.mkdir(parents=True, exist_ok=True)
    title = v.get("title") or vid
    md = t_dir / f"{vid}.md"
    md.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")

    v["asr"] = {"status": "done", "task_id": v.get("asr", {}).get("task_id"),
                "source": cfg.get("dashscope", {}).get("model", "paraformer-v2"),
                "duration_seconds": duration, "transcript_chars": len(text)}
    v["transcript"] = text
    v["transcript_file"] = str(md.relative_to(ws))
    v["stage"] = "transcribed"
    return len(text)


def reuse_library_transcripts(cfg, vids):
    """config.transcript_library 指向导出线素材库根目录时，按 aweme_id 复用已有逐字稿。"""
    lib = (cfg.get("transcript_library") or "").strip()
    if not lib:
        return 0
    lib = Path(lib).expanduser()
    if not lib.is_dir():
        print(f"[提示] transcript_library 目录不存在：{lib}")
        return 0
    # 索引：博主目录/links.json → {aweme_id: (博主目录, post_id)}
    vid_index = {}
    for links_file in lib.glob("*/links.json"):
        try:
            links = json.loads(links_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for pid, url in links.items():
            aid = extract_video_id(url or "")
            if aid and aid not in vid_index:
                vid_index[aid] = (links_file.parent, pid)
    reused = 0
    for v in vids.values():
        if v.get("asr", {}).get("status") == "done":
            continue
        aid = extract_video_id(v.get("share_url") or v.get("page_url") or "")
        hit = vid_index.get(aid) if aid else None
        if not hit:
            continue
        bdir, pid = hit
        mds = list(bdir.glob(f"???_{pid}_*.md")) or list(bdir.glob(f"*_{pid}_*.md"))
        if not mds:
            continue
        text = mds[0].read_text(encoding="utf-8")
        body = re.sub(r"^>.*$|^#+\s.*$|^---$|^$", "", text, flags=re.M).strip()
        if len(body) < 50:
            continue
        v["transcript"] = body
        v["transcript_file"] = str(mds[0])
        v["asr"] = {"status": "done", "source": f"biji-library:{mds[0].parent.name}",
                    "duration_seconds": None, "transcript_chars": len(body)}
        v["stage"] = "transcribed"
        reused += 1
        print(f"  [复用逐字稿] {v.get('title') or aid} ← {mds[0].parent.name}/（跳过转写）")
    if reused:
        store_save(cfg, {"videos": vids, "updated_at": now_str()})
    return reused


def main():
    ap = argparse.ArgumentParser(description="Paraformer 批量转写")
    ap.add_argument("--config", help="指定 config.json 路径")
    ap.add_argument("--video-id", help="只转写指定 video_id（可选）")
    ap.add_argument("--resubmit", action="store_true",
                    help="忽略已保存的 task_id 重新提交（谨慎：会重新计费）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    d = cfg.get("dashscope", {})
    store = store_load(cfg)
    vids = store["videos"]

    # 0) 逐字稿库复用：导出线（Get笔记）已转写过的视频，按 aweme_id 匹配直接复用，省转写费
    reused = reuse_library_transcripts(cfg, vids)

    # 待处理：有直链、未完成转写、未报永久错误
    pending = {}
    for vid, v in vids.items():
        if args.video_id and vid != args.video_id:
            continue
        if not v.get("video_file_url"):
            continue
        asr = v.get("asr") or {}
        if asr.get("status") == "done":
            continue
        if asr.get("status") == "failed" and not args.video_id and not args.resubmit:
            continue
        pending[vid] = v
    if not pending:
        print("[完成] 没有待转写条目（库复用 %d 条已生效，其余均已完成）。接着跑 merge_output.py 合并。" % reused)
        return

    key = (d.get("api_key") or "").strip()
    if not key:
        raise SystemExit("[提示] 未配置 DashScope API Key，跳过在线转写（库复用的 "
                         f"{reused} 条已完成，还有 {len(pending)} 条待转写）。"
                         "需要时再填 key：百炼控制台 → API-KEY（sk- 开头）")

    # 阶段一：提交（没有 task_id 的）
    for vid, v in pending.items():
        asr = v.setdefault("asr", {"status": "pending"})
        if asr.get("task_id") and not args.resubmit:
            continue
        try:
            asr["task_id"] = submit(cfg, key, v["video_file_url"])
            asr["status"] = "submitted"
            print(f"  [已提交] {vid} → task {asr['task_id']}")
        except Exception as e:
            asr.update(status="failed", error=str(e)[:300])
            print(f"  [提交失败] {vid}：{e}")
        store_save(cfg, store)
        time.sleep(1)

    # 阶段二：轮询全部
    interval = int(d.get("poll_interval_seconds", 10))
    max_wait = int(d.get("max_wait_seconds", 1800))
    start = time.time()
    while True:
        alive = [v for v in pending.values() if v["asr"].get("status") in ("submitted", "running")]
        if not alive or time.time() - start > max_wait:
            break
        for v in alive:
            vid = v["video_id"]
            try:
                resp = query(cfg, key, v["asr"]["task_id"])
            except Exception as e:
                v["asr"]["status"] = "failed"
                v["asr"]["error"] = str(e)[:300]
                print(f"  [查询失败] {vid}：{e}")
                continue
            status = deep_get(resp, "output.task_status")
            v["asr"]["status"] = "running" if status in ("PENDING", "RUNNING") else status.lower()
            if status == "SUCCEEDED":
                res = (deep_get(resp, "output.results") or [{}])[0]
                if res.get("subtask_status") == "SUCCEEDED":
                    turl = res.get("transcription_url")
                    tmp = Path(cfg["workspace"]) / ".raw_asr" / f"{vid}.tmp.json"
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    http_download(turl, tmp)
                    n = save_result(cfg, v, json.loads(tmp.read_text(encoding="utf-8")))
                    tmp.unlink(missing_ok=True)
                    print(f"  [转写完成] {vid}（{n} 字）")
                else:
                    code = res.get("code", "UNKNOWN")
                    hint = ERROR_HINTS.get(code, "")
                    v["asr"].update(status="failed", error=f"{code}: {res.get('message', '')}")
                    print(f"  [转写失败] {vid}：{code} {res.get('message', '')} {hint}")
            elif status in ("FAILED", "CANCELED", "UNKNOWN"):
                v["asr"].update(status="failed",
                                error=json.dumps(deep_get(resp, "output") or resp, ensure_ascii=False)[:300])
                print(f"  [任务失败] {vid}：{v['asr']['error']}")
        store_save(cfg, store)
        alive = [v for v in pending.values() if v["asr"].get("status") in ("submitted", "running")]
        if alive:
            first = min(5, interval)
            print(f"  … {len(alive)} 个任务进行中，{first}s 后再查")
            time.sleep(first)
            interval = int(d.get("poll_interval_seconds", 10))

    store["updated_at"] = now_str()
    store_save(cfg, store)
    done = sum(1 for v in pending.values() if v.get("asr", {}).get("status") == "done")
    fail = sum(1 for v in pending.values() if v.get("asr", {}).get("status") == "failed")
    print(f"[完成] 本批转写成功 {done} / 失败 {fail}。逐字稿在 {cfg['workspace']}/transcripts/，"
          f"接着跑 merge_output.py 合并数据。")


if __name__ == "__main__":
    main()
