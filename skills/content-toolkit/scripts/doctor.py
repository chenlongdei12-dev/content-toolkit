#!/usr/bin/env python3
"""环境自检 + 凭据验证（content-toolkit 第一条命令，全部零成本探测）。

用法：python3 doctor.py [--fix]
输出 ✅/❌ 清单和对应修复方法；--fix 时直接打印可粘贴的修复命令。
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import EXAMPLE_CONFIG_PATH, CONFIG_PATH, load_config

PY_URL = "https://www.python.org/downloads/"
DASHSCOPE_URL = "https://bailian.console.aliyun.com/?tab=model#/api-key"
MONID_URL = "https://app.monid.ai/access/api-keys"

results = []


def check(name, ok, detail="", fix=None):
    results.append((name, ok, detail, fix))


def http(url, headers=None, timeout=12, method="GET", body=None):
    req = urllib.request.Request(url, headers=headers or {}, method=method,
                                 data=(json.dumps(body).encode() if isinstance(body, dict) else body))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main():
    fix_mode = "--fix" in sys.argv

    # 1. Python 版本
    ok = sys.version_info >= (3, 9)
    check("Python ≥ 3.9", ok, sys.version.split()[0],
          None if ok else f"安装新版 Python：{PY_URL}（macOS 可 brew install python）")

    # 2. 配置文件
    cfg = load_config()
    has_cfg = CONFIG_PATH.exists()
    check("config.json 已创建", has_cfg,
          str(CONFIG_PATH),
          None if has_cfg else f"cp {EXAMPLE_CONFIG_PATH.name} config.json 后填入你的 key（教程见 README）")

    # 3. DashScope key（零成本验证：查一个不存在的任务号，鉴权过即 key 有效）
    key = (cfg.get("dashscope", {}).get("api_key") or "").strip()
    if not key:
        check("阿里云百炼 Key", False, "未填写", f"到 {DASHSCOPE_URL} 创建（sk- 开头），填入 config.json 的 dashscope.api_key")
    else:
        try:
            http("https://dashscope.aliyuncs.com/api/v1/tasks/00000000-0000-0000-0000-000000000000",
                 headers={"Authorization": f"Bearer {key}"}, method="POST")
            check("阿里云百炼 Key", True, "有效（sk-…%s）" % key[-4:])
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                check("阿里云百炼 Key", True, "有效（sk-…%s）" % key[-4:])
            elif e.code == 401:
                check("阿里云百炼 Key", False, "无效（401）",
                      f"确认是百炼控制台的 sk- 开头 Key（不是阿里云 RAM AccessKey）：{DASHSCOPE_URL}")
            else:
                check("阿里云百炼 Key", False, f"HTTP {e.code}", "看 detail 或稍后重试")
        except Exception as e:
            check("阿里云百炼 Key", False, f"网络错误：{e}", "检查网络/代理后重试")

    # 4. Monid key（零成本验证：查余额）
    mk = (cfg.get("monid", {}).get("token") or "").strip()
    if not mk:
        check("Monid Key", False, "未填写（监控流水线必需）",
              f"到 {MONID_URL} 注册并创建（monid_live_ 开头，新号送 $1 额度），填入 config.json 的 monid.token")
    else:
        try:
            st, body = http("https://api.monid.ai/v1/wallet/balance",
                            headers={"Authorization": f"Bearer {mk}"})
            bal = json.loads(body)["balance"]["value"]
            check("Monid Key", True, f"有效，余额 ${bal:.2f}",
                  f"余额不足时到 https://app.monid.ai/wallet 充值（每次采集约 $0.0012）" if bal < 0.1 else None)
        except Exception as e:
            check("Monid Key", False, str(e)[:80], f"确认 key 正确：{MONID_URL}")

    # 5. zhuceka 去水印（选填；只查是否配置，不实际调用）
    p = cfg.get("parser", {})
    tpl = p.get("url_template") or ""
    check("zhuceka 去水印兜底（选填）", "uid=" in tpl and "key=" in tpl,
          "已配置" if "uid=" in tpl else "未配置（Monid 去水印为主，这个是备用）",
          None if "uid=" in tpl else "在 api.zhuceka.cn 注册后把 uid/key 填入 config.json 的 parser.url_template")

    # 6. playwright（仅导出流水线的 Get笔记线需要）
    try:
        import playwright  # noqa
        check("playwright（选填，Get笔记导出用）", True, "已安装")
    except ImportError:
        check("playwright（选填，Get笔记导出用）", False, "未安装（不用导出流水线可忽略）",
              "pip3 install --user playwright && python3 -m playwright install chromium")

    # 7. 网络（服务器有任何响应就算可达，包括 404）
    for name, url in (("阿里云 API 可达", "https://dashscope.aliyuncs.com"),
                      ("Monid API 可达", "https://api.monid.ai")):
        try:
            http(url, timeout=8)
            check(name, True)
        except urllib.error.HTTPError:
            check(name, True)  # 有 HTTP 响应 = 网络通
        except Exception as e:
            check(name, False, str(e)[:60], "检查网络/VPN/代理")

    # 汇总
    print("\n===== content-toolkit 自检 =====")
    fails = 0
    for name, ok, detail, fix in results:
        mark = "✅" if ok else "❌"
        line = f"{mark} {name}" + (f"  — {detail}" if detail else "")
        print(line)
        if not ok and fix:
            fails += 1
            print(f"   ↳ 修复：{fix}")
    core_fail = sum(1 for n, ok, *_ in results if not ok and "选填" not in n and "可忽略" not in n)
    print()
    if core_fail == 0:
        print("🟢 核心项全通过。快速体验：python3 run.py monitor --links \"<一条抖音视频链接>\"")
    else:
        print(f"🔴 有 {core_fail} 个核心项待解决（上面每行 ↳ 是修复方法）。解决后重跑本命令。")
    return 1 if core_fail else 0


if __name__ == "__main__":
    sys.exit(main())
