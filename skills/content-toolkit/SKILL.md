---
name: content-toolkit
description: 内容采集工具箱：两条流水线把抖音博主内容变成「逐字稿+数据」的 Markdown 素材库。① 监控流水线：给博主 sec_user_id 或视频链接 → Monid 采集数据 → 去水印拿直链 → 阿里云 Paraformer 转写 → 合并出稿；② 导出流水线：Get笔记(得到大脑)订阅博主逐字稿批量导出 + 社媒助手作品数据 → 合并。当用户说 监控博主/对标账号/出逐字稿/转写视频/导出得到大脑/Get笔记/合并点赞评论数据/批量导文案 时使用。首次使用先跑 doctor.py 自检。
---

# content-toolkit — 内容采集工具箱

两条流水线，一个终点：`逐字稿 + 数据` 的 Markdown 素材库（frontmatter 数据 + 正文 + INDEX 索引）。

| | 监控流水线 | 导出流水线 |
| --- | --- | --- |
| 适合 | 持续盯博主、只要最新 N 条、有链接就行 | 一次性导出博主**全部**历史内容 |
| 来源 | Monid 网关（抖音数据+无水印直链） | Get笔记/得到大脑订阅 + 社媒助手插件 |
| 详见 | `references/pipeline-monitor.md` | `references/pipeline-export.md` |

## 第一步永远是自检

```bash
cd ~/.claude/skills/content-toolkit/scripts
python3 doctor.py
```

❌ 项照着 ↳ 提示修（key 获取教程在安装包 README.md）。全 ✅ 再往下。

## 常用命令（scripts/ 下，或用 run.py 一条龙）

```bash
# === 监控流水线 ===
python3 run.py monitor --links "https://v.douyin.com/xxxx/"     # 几条链接直接出稿
python3 run.py monitor --blogger-sec-uid MS4wLjAB...            # 盯一个博主（加入监控列表）
python3 run.py monitor                                           # 跑监控列表里所有博主

# === 导出流水线 ===
python3 run.py export-biji "谢胜子" --with-data                  # 名字模糊匹配，导完自动合并
python3 run.py export-data "https://www.douyin.com/user/MS4..." # 社媒助手自动导数据
python3 run.py export-merge 谢胜子                               # 单独合并逐字稿+数据

# 分步执行（run.py 的每一步也可单独跑，全部幂等可断点续跑）：
#   监控：monid_fetch.py → parse_video_url.py → asr_transcribe.py → merge_output.py
#   导出：biji_export.py(topics/follows/export) → social_stats.py → merge_export.py
```

## 核心机制（agent 必读，30 秒）

- **幂等状态库**：监控流水线所有步骤读写 `<workspace>/videos.json`（阶段 collected→parsed→transcribed→merged），中断重跑零成本；导出流水线按文件名里的 post_id 去重，增量续传
- **计费**：Monid 每次调用 $0.0012（user_posts/douyin.video 各一次/条）；阿里云按语音时长计费（约每小时音频几毛钱量级）。task_id 都会持久化，重跑不重复扣费
- **时效**：抖音无水印直链几小时失效——parse 完尽快转写，别隔天
- **纯 BGM 无语音的视频**转写报 `SUCCESS_WITH_NO_VALID_FRAGMENT` 属正常，跳过即可

## 排错速查

| 现象 | 处理 |
| --- | --- |
| doctor ❌ | 照 ↳ 提示修；key 无效多数是填错了类型（百炼要 sk-，Monid 要 monid_live_） |
| InvalidFile.DownloadFailed | 直链过期/防盗链 → 重跑 parse 再立即转写；或换 parser 接口 |
| Throttling/限流 | 稍后重跑（断点续传，不重复计费） |
| Get笔记 403 反复 | token 刷新失败 → `python3 biji_export.py login`（人在场，一次） |
| 社媒数据匹配率低 | 看 INDEX 尾部未匹配清单；标题差异大时调 merge_export.py 阈值 |
| 更多 | `references/pipeline-*.md` 各有排错章节 |

## 其他内容类型

公众号/图片/聊天记录/直播回放等 10 类内容的采集方法见 `references/methodology.md`（用户问「某类内容怎么采集」时先查它）。
