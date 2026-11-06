# INSTALL.md — 给 AI Agent 的安装指令

你的用户想安装 content-toolkit。按下面的顺序执行，遇到问题优先看文末排错表。

## 1. 安装 skill

```bash
# 把 skills/content-toolkit 复制到用户的 agent skills 目录（Claude Code 默认）：
mkdir -p ~/.claude/skills
cp -r <本文件夹路径>/skills/content-toolkit ~/.claude/skills/
# 其他 agent（OpenClaw/Codex 等）放到对应的 skills 目录，结构不变。
```

只需 Python ≥3.9（macOS 自带）；监控流水线零第三方依赖。

## 2. 创建配置并自检

```bash
cd ~/.claude/skills/content-toolkit
cp config.example.json config.json
cd scripts && python3 doctor.py
```

按 doctor 的 ❌↳ 提示引导用户逐项解决（别替用户编 key，让用户自己注册，README 里有教程链接）。
两个核心 key：`dashscope.api_key`（百炼 sk- 开头）、`monid.token`（monid_live_ 开头）。填完重跑 doctor 直到核心项全 ✅。

## 3. 冒烟测试（花不到 1 分钱）

让用户给一条抖音视频链接，然后：

```bash
cd ~/.claude/skills/content-toolkit/scripts
python3 run.py monitor --links "<用户给的链接>"
```

成功标准：`~/VideoMonitor/` 下出现博主名目录（.md 逐字稿+数据）和 INDEX.md。把产出路径告诉用户。

## 4.（可选）导出流水线的额外设置

用户要「导出博主全部历史内容」时才需要：
- Get笔记线：`pip3 install --user playwright && python3 -m playwright install chromium`，然后 `python3 biji_export.py login`（需要用户在场扫码）
- 社媒助手自动线（macOS）：搭建专用 Chrome 实例并装插件登录，见 `references/pipeline-export.md`

## 排错表

| 症状 | 处理 |
| --- | --- |
| pip 装 playwright 报 externally-managed | 加 `--user`，或 `pip3 install --break-system-packages --user playwright` |
| doctor 全是网络错误 | 用户开了 VPN/代理，让用户关掉或给终端配代理后重跑 |
| 百炼 key 填了 RAM AccessKey | 那是错的：要去百炼控制台单独创建 API Key（sk- 开头） |
| 转写报 SUCCESS_WITH_NO_VALID_FRAGMENT | 视频纯音乐无人声，正常，换条有说话的视频测试 |
| 用户问怎么获取 sec_user_id | 打开博主抖音主页，链接 `douyin.com/user/` 后面那一长串就是 |
| run.py monitor 没有新条目 | 正常（监控列表里的都处理过了）；给 `--links` 或加新博主 |
