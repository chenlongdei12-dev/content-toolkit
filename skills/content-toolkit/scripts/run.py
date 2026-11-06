#!/usr/bin/env python3
"""content-toolkit 统一入口：一条命令跑完整条流水线。

监控流水线（抖音博主 → 逐字稿+数据）：
  python3 run.py monitor --blogger-sec-uid MS4wLjAB...      # 拉博主最新视频并全链处理
  python3 run.py monitor --links "链接1,链接2"              # 直接处理几条链接
  步骤：采集(Monid) → 去水印(拿直链) → 阿里云转写 → 合并出 Markdown+INDEX

导出流水线（Get笔记/得到大脑 订阅博主 → 逐字稿+数据）：
  python3 run.py export-biji "谢胜子"                       # 按博主名增量导出（先 login 一次）
  python3 run.py export-data "https://www.douyin.com/user/MS4..."   # 社媒助手自动导出数据 xlsx
  python3 run.py export-merge 谢胜子                        # 合并逐字稿+数据（自动找最新 xlsx）

自检：python3 doctor.py
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sh(cmd, desc, must=True):
    """跑子脚本；must=True 时失败即停。"""
    print(f"\n▶ {desc}\n  $ {cmd}", flush=True)
    r = subprocess.run(cmd, shell=True, cwd=HERE)
    if r.returncode != 0 and must:
        print(f"\n✗ 「{desc}」失败（退出码 {r.returncode}），已停止。上面输出里有原因。")
        sys.exit(r.returncode)
    return r.returncode


def cmd_monitor(args):
    if args.links:
        sh(f'python3 monid_fetch.py --links "{args.links}"', "步骤1/4 采集视频信息")
    elif args.blogger_sec_uid:
        cfg = json.loads((HERE.parent / "config.json").read_text(encoding="utf-8")) \
            if (HERE.parent / "config.json").exists() else {}
        watch = cfg.setdefault("monid", {}).setdefault("watch_sec_user_ids", [])
        if args.blogger_sec_uid not in watch:
            watch.append(args.blogger_sec_uid)
            (HERE.parent / "config.json").write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"已把博主加入 config.json 的监控列表：{args.blogger_sec_uid}")
        sh("python3 monid_fetch.py", "步骤1/4 从 Monid 拉取博主最新视频")
    else:
        sh("python3 monid_fetch.py", "步骤1/4 从 Monid 拉取监控列表博主的最新视频")
    sh("python3 parse_video_url.py", "步骤2/4 去水印解析视频直链（已是直链自动跳过）")
    sh("python3 asr_transcribe.py", "步骤3/4 阿里云 Paraformer 转写（断点续跑，不重复计费）")
    sh("python3 merge_output.py", "步骤4/4 合并数据与逐字稿")


def cmd_export_biji(args):
    # 按名字找博主：topics → follows 匹配
    out = subprocess.run('python3 biji_export.py topics', shell=True, cwd=HERE,
                         capture_output=True, text=True)
    try:
        topics = json.loads(out.stdout)["items"]
    except Exception:
        print("topics 拉取失败：", out.stdout, out.stderr)
        sys.exit(2)
    target = None
    for t in topics:
        fo = subprocess.run(f'python3 biji_export.py follows "{t["alias"]}"',
                            shell=True, cwd=HERE, capture_output=True, text=True)
        try:
            for f in json.loads(fo.stdout).get("items", []):
                if args.name in f["name"]:
                    target = f
                    break
        except Exception:
            pass
        if target:
            break
    if not target:
        print(f"在 {len(topics)} 个知识库里没找到名字含「{args.name}」的博主。"
              f"跑 `python3 biji_export.py topics` 看知识库，或直接用 URL："
              f"python3 biji_export.py export \"<url>\"")
        sys.exit(2)
    print(f"找到博主：{target['name']}（{target.get('post_count')} 篇）")
    limit = f" --max-items {args.max_items}" if args.max_items else ""
    sh(f'python3 biji_export.py export "{target["url"]}"{limit}',
       f"增量导出逐字稿（{target['name']}）")
    if args.with_data:
        cmd_export_merge(argparse.Namespace(name=target["name"], transcript_dir=None, stats=None))


def cmd_export_data(args):
    sh(f'python3 shejiao_export.py "{args.url}" --count {args.count}',
       "社媒助手自动导出达人作品数据（需要专用 Chrome 已装插件登录，见 references/pipeline-export.md）")


def latest_xlsx(name):
    pats = [os.path.expanduser(f"~/Downloads/{name}_作品数据_*.xlsx")]
    files = sorted(sum((glob.glob(p) for p in pats), []), key=os.path.getmtime)
    if not files and name:  # 兜底：按达人名模糊找
        files = sorted(glob.glob(os.path.expanduser(f"~/Downloads/*{name}*作品数据*.xlsx")),
                       key=os.path.getmtime)
    return files[-1] if files else None


def cmd_export_merge(args):
    # 找逐字稿目录：默认导出根目录下 {名字}_*（biji_export 的目录命名）
    tdir = Path(args.transcript_dir) if args.transcript_dir else None
    if tdir is None:
        base = Path.home() / "DouClaw" / "Get笔记博主知识库"
        # 也兼容自定义导出位置
        import biji_export
        base = Path(biji_export.DEFAULT_BASE)
        cands = sorted(base.glob(f"{args.name}_*"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
        if not cands:
            print(f"没找到 {base}/{args.name}_* 目录；先跑 export-biji，或用 --transcript-dir 指定。")
            sys.exit(2)
        tdir = cands[-1]
    stats = args.stats
    if not stats:
        x = latest_xlsx(args.name)
        if not x:
            print(f"~/Downloads 里没有「{args.name}」的作品数据 xlsx。"
                  f"先跑 export-data 或手动用社媒助手导出。")
            sys.exit(2)
        stats = "/tmp/_stats.json"
        sh(f'python3 social_stats.py "{x}" -o {stats}', f"解析社媒数据（{Path(x).name}）")
    sh(f'python3 merge_export.py --transcripts-dir "{tdir}" --stats "{stats}"', "合并文案与数据")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("monitor", help="监控流水线：抖音博主 → 逐字稿+数据")
    m.add_argument("--links", help="直接给视频链接（逗号分隔）")
    m.add_argument("--blogger-sec-uid", help="博主 sec_user_id（自动加入监控列表）")
    m.set_defaults(func=cmd_monitor)

    b = sub.add_parser("export-biji", help="Get笔记订阅博主逐字稿增量导出")
    b.add_argument("name", help="博主名（模糊匹配）")
    b.add_argument("--max-items", type=int, help="本次最多导出篇数")
    b.add_argument("--with-data", action="store_true", help="导出完自动找数据并合并")
    b.set_defaults(func=cmd_export_biji)

    d = sub.add_parser("export-data", help="社媒助手自动导出达人作品数据 xlsx")
    d.add_argument("url", help="抖音达人主页 URL")
    d.add_argument("--count", type=int, default=0, help="导出数量，0=全部")
    d.set_defaults(func=cmd_export_data)

    g = sub.add_parser("export-merge", help="合并逐字稿+作品数据")
    g.add_argument("name", help="博主名（用于定位目录和 xlsx）")
    g.add_argument("--transcript-dir")
    g.add_argument("--stats", help="social_stats 输出 json（默认自动解析最新 xlsx）")
    g.set_defaults(func=cmd_export_merge)

    args = ap.parse_args()
    t0 = time.time()
    args.func(args)
    print(f"\n✔ 全部完成，用时 {time.time()-t0:.0f} 秒。")


if __name__ == "__main__":
    main()
