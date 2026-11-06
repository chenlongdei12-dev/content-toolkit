#!/usr/bin/env python3
"""环境自检（MVP 分级引导）：先看零 key 能用什么，再按需解锁，不吓唬新手。

用法：python3 doctor.py
原则：第一次使用只需要最少的 key——导出流水线零 key 可用（登录得到大脑即可）；
监控流水线才需要 百炼+Monid 两个 key。全部探测零成本。
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG_PATH, EXAMPLE_CONFIG_PATH, cost_total, load_config

DASHSCOPE_URL = "https://bailian.console.aliyun.com/?tab=model#/api-key"
MONID_URL = "https://app.monid.ai/access/api-keys"


def http(url, headers=None, timeout=12, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def reachable(url):
    try:
        http(url, timeout=8)
        return True
    except urllib.error.HTTPError:
        return True  # 有 HTTP 响应 = 网络通
    except Exception:
        return False


def main():
    cfg = load_config()
    lines = []
    lines.append("\n===== content-toolkit 自检 =====")

    # 基础
    py_ok = sys.version_info >= (3, 9)
    lines.append(f"{'✅' if py_ok else '❌'} Python ≥ 3.9  — {sys.version.split()[0]}")
    if not py_ok:
        lines.append("   ↳ 升级 Python：https://www.python.org/downloads/")
    cfg_ok = CONFIG_PATH.exists()
    lines.append(f"{'✅' if cfg_ok else '⚠️ '} config.json  — {'已创建' if cfg_ok else '还没建（cp config.example.json config.json）'}")

    # ===== 能力一：导出流水线（零 key）=====
    lines.append("\n📦 导出流水线（博主全部历史逐字稿）——零 API key：")
    cred = Path.home() / ".biji_exporter" / "skill_credentials.json"
    logged = cred.exists()
    lines.append(f"   {'✅' if logged else '⬜'} 得到大脑(Get笔记)登录 — "
                 f"{'已登录' if logged else '未登录：python3 biji_export.py login（扫码，一次）'}")
    try:
        import playwright  # noqa
        pw = True
    except ImportError:
        pw = False
    if logged and not pw:
        lines.append("   ⬜ playwright 未装（登录/自动刷新需要）：pip3 install --user playwright && python3 -m playwright install chromium")
    lines.append("   " + ("✅ 可用" if logged else "⬜ 待登录后可用") +
                 "：python3 run.py export-biji \"<博主名>\"")

    # ===== 能力二：监控流水线（2 个 key）=====
    lines.append("\n📦 监控流水线（链接/盯博主 → 逐字稿+数据）——需要 2 个 key：")
    ds = (cfg.get("dashscope", {}).get("api_key") or "").strip()
    mk = (cfg.get("monid", {}).get("token") or "").strip()
    if ds:
        try:
            http("https://dashscope.aliyuncs.com/api/v1/tasks/00000000-0000-0000-0000-000000000000",
                 headers={"Authorization": f"Bearer {ds}"}, method="POST")
            ds_ok, ds_msg = True, f"有效（sk-…{ds[-4:]}）"
        except urllib.error.HTTPError as e:
            ds_ok, ds_msg = (e.code in (400, 404)), ("有效" if e.code in (400, 404) else f"HTTP {e.code}")
        except Exception as e:
            ds_ok, ds_msg = False, f"网络错误 {str(e)[:40]}"
    else:
        ds_ok, ds_msg = False, "未填写"
    lines.append(f"   {'✅' if ds_ok else '⬜'} 阿里云百炼 Key（转写） — {ds_msg}")
    if not ds_ok:
        lines.append(f"      ↳ {DASHSCOPE_URL} 注册创建（sk- 开头，有免费额度）")
    if mk:
        try:
            bal = json.loads(http("https://api.monid.ai/v1/wallet/balance",
                                  headers={"Authorization": f"Bearer {mk}"}))["balance"]["value"]
            mk_ok, mk_msg = True, f"有效，余额 ${bal:.2f}"
        except Exception as e:
            mk_ok, mk_msg = False, str(e)[:60]
    else:
        mk_ok, mk_msg = False, "未填写"
    lines.append(f"   {'✅' if mk_ok else '⬜'} Monid Key（抖音数据） — {mk_msg}")
    if not mk_ok:
        lines.append(f"      ↳ {MONID_URL} 注册创建（monid_live_ 开头，送 $1 额度）")
    if ds_ok and mk_ok:
        lines.append("   ✅ 可用：python3 run.py monitor --links \"<视频链接>\"")
    else:
        lines.append("   ⬜ 补齐上面 key 后解锁（每个都有免费额度，注册各约 2 分钟）")

    # ===== 网络 =====
    net = reachable("https://api.monid.ai")
    if not net:
        lines.append("\n❌ 外网不可达 — 检查网络/VPN")

    # ===== 花费台账 =====
    total, n = cost_total(cfg)
    if total:
        lines.append(f"\n💰 累计 Monid 花费：${total:.4f}（{n} 次调用）")

    print("\n".join(lines))
    if not py_ok:
        return 1
    print("\n🟢 建议：先零 key 跑导出线体验；想要「丢链接出稿」再补两个 key。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
