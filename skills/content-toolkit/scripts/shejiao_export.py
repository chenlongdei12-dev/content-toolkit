#!/usr/bin/env python3
"""社媒助手自动导出：在专用 Chrome 实例里驱动插件，导出抖音达人全部视频数据 xlsx。

前置（一次性，已完成）：
  专用实例:  open -na "Google Chrome" --args --user-data-dir="$HOME/.shejiao_automation" \
             --remote-debugging-port=9222 --no-first-run --no-default-browser-check
  （Chrome 136+ 禁止在默认用户目录开调试端口，所以必须独立 user-data-dir；
    插件社媒助手 + 抖音登录 + 社媒助手账号均保存在该实例里）

用法：
  python3 shejiao_export.py "https://www.douyin.com/user/MS4wLj..." [--count 100] [--timeout 1800]

输出：~/Downloads/{达人昵称}_作品数据_YYYYMMDD.xlsx
"""
import argparse
import glob
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
EXT = "iecafjejbggeoldcjiehgoolokaebpdf"
SIDEPANEL = f"chrome-extension://{EXT}/sidepanel.html"
DL = os.path.expanduser("~/Downloads")


def find_page(ctx, pred):
    for pg in ctx.pages:
        try:
            if pred(pg):
                return pg
        except Exception:
            pass
    return None


def wait_new_xlsx(before, timeout_s=60):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        cr = glob.glob(DL + "/*.crdownload")
        new = set(glob.glob(DL + "/*.xls*")) - before
        if new and not cr:
            f = sorted(new, key=os.path.getmtime)[-1]
            if os.path.getsize(f) > 0:
                return f
        time.sleep(2)
    return None


def chrome_binary():
    """跨平台找 Chrome 可执行文件（Windows/Linux 兼容）。"""
    import platform
    import shutil
    sysname = platform.system()
    if sysname == "Windows":
        for p in (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                  os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                  os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")):
            if os.path.exists(p):
                return p
        return None
    if sysname == "Darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return shutil.which("google-chrome") or shutil.which("chromium")


def launch_instance():
    """跨平台拉起专用 Chrome 实例（独立 user-data-dir + CDP 端口）。"""
    import platform
    import subprocess
    data = os.path.expanduser("~/.shejiao_automation")
    args = [f"--user-data-dir={data}", "--remote-debugging-port=9222",
            "--no-first-run", "--no-default-browser-check"]
    if platform.system() == "Darwin":
        subprocess.run(["open", "-na", "Google Chrome", "--args", *args], check=False)
    else:
        exe = chrome_binary()
        if not exe:
            sys.exit(json.dumps({"ok": False,
                                 "error": "找不到 Google Chrome，请先安装（windows 需关闭已在运行的 Chrome 后重试）"},
                                ensure_ascii=False))
        subprocess.Popen([exe, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="抖音达人主页 URL")
    ap.add_argument("--count", type=int, default=0, help="导出数量，0=全部")
    ap.add_argument("--timeout", type=int, default=1800, help="采集最长等待秒数")
    args = ap.parse_args()

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP)
        except Exception:
            launch_instance()          # 实例没开就自动拉起（登录态都在，无需人工）
            time.sleep(8)
            try:
                browser = p.chromium.connect_over_cdp(CDP)
            except Exception as e:
                sys.exit(json.dumps({"ok": False,
                                     "error": f"连不上 {CDP}：{e}；自动拉起失败，检查 Chrome 是否被占用"},
                                    ensure_ascii=False))
        # 关键：不让 Playwright 把下载劫持进临时 artifacts 目录（会被自动清理）
        cdp = browser.new_browser_cdp_session()
        cdp.send("Browser.setDownloadBehavior",
                 {"behavior": "allow", "downloadPath": DL, "eventsEnabled": True})
        ctx = browser.contexts[0]

        # 1. sidepanel：恰好保留一个标签（插件不会自己开；没有对话框就没有落点）
        #    实测要点：已存在的标签直接用、绝不 goto 重载——重载后界面正常但「开始采集」建不起任务
        sps = [pg for pg in ctx.pages if EXT in pg.url]
        if not sps:
            sp = ctx.new_page()
            sp.goto(SIDEPANEL)
            sp.wait_for_timeout(2000)
        else:
            sp = sps[0]
            for extra in sps[1:]:
                extra.close()

        # 2. 打开达人主页 → 点注入面板里的「导出视频」
        dy = find_page(ctx, lambda pg: "douyin.com/user/" in pg.url) or ctx.new_page()
        dy.bring_to_front()
        dy.goto(args.url, wait_until="domcontentloaded")
        dy.wait_for_timeout(5000)
        clicked = dy.evaluate("""() => {
          for (const h of [...document.body.querySelectorAll('*')].filter(el => el.shadowRoot)) {
            const btn = [...h.shadowRoot.querySelectorAll(
              'button,[role=button],div[class*=btn],span[class*=btn]')]
              .find(b => (b.innerText||'').trim() === '导出视频');
            if (btn) { btn.click(); return true }
          }
          return false
        }""")
        if not clicked:
            sys.exit(json.dumps({"ok": False, "error": "达人主页上没找到社媒助手「导出视频」按钮"}, ensure_ascii=False))

        # 3. sidepanel 里确认数量 → 开始采集
        sp.bring_to_front()
        sp.wait_for_timeout(2000)
        if args.count > 0:
            sp.evaluate("""(n) => {
              const num = [...document.querySelectorAll('input')]
                .find(i => i.type==='number' || /^\\d+$/.test(i.value||''));
              if (num) { const set = Object.getOwnPropertyDescriptor(
                  window.HTMLInputElement.prototype,'value').set;
                set.call(num, String(n)); num.dispatchEvent(new Event('input',{bubbles:true})) }
            }""", args.count)
        try:
            sp.get_by_text("开始采集", exact=True).first.click(timeout=8000)
        except Exception as e:
            sys.exit(json.dumps({"ok": False,
                                 "error": f"sidepanel 里没找到「开始采集」（插件登录态失效？）：{e}"},
                                ensure_ascii=False))
        print("已开始采集，等待完成…", file=sys.stderr)

        # 4. 轮询进度
        deadline = time.time() + args.timeout
        total = None
        while time.time() < deadline:
            txt = sp.evaluate("document.body.innerText")
            m = re.search(r"已完成\s*(\d+)\s*/\s*(\d+)", txt)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                print(f"\r进度 {done}/{total}", end="", file=sys.stderr)
                if done == total and "处理完成" in txt:
                    break
            elif "处理完成" in txt:
                break
            time.sleep(15)
        else:
            sys.exit(json.dumps({"ok": False, "error": f"采集超时（{args.timeout}s）"}, ensure_ascii=False))

        # 5. 导出 xlsx（真实点击满足用户手势要求）
        before = set(glob.glob(DL + "/*.xls*"))
        sp.bring_to_front()
        sp.get_by_text("导出Excel数据", exact=True).first.click(timeout=8000)
        f = wait_new_xlsx(before)
        if not f:
            sys.exit(json.dumps({"ok": False, "error": "点击导出后 60 秒内没有新 xlsx 落盘"}, ensure_ascii=False))

        nick = (re.search(r"^(.+?)的抖音", dy.title()).group(1)
                if re.search(r"的抖音", dy.title()) else "达人")
        out = os.path.join(DL, f"{nick}_作品数据_{time.strftime('%Y%m%d')}.xlsx")
        os.rename(f, out)
        print(json.dumps({"ok": True, "file": out, "rows": total,
                          "size": os.path.getsize(out)}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    main()
