# 监控流水线详解（Monid → 去水印 → 转写 → 合并）

```
Monid 采集(数据+链接) ──► 去水印解析(拿视频直链) ──► 阿里云Paraformer转写 ──► 数据+文案合并
      步骤1                    步骤2                    步骤3                步骤4
  monid_fetch.py          parse_video_url.py       asr_transcribe.py    merge_output.py
```

## 步骤与脚本

| 步骤 | 脚本 | 入口 | 产出 |
| --- | --- | --- | --- |
| 1 采集 | monid_fetch.py | `--monid`（监控列表）/ `--links "url1,url2"` / `--file 导出.json` | videos.json（状态库） |
| 2 去水印 | parse_video_url.py | 自动处理无直链条目 | video_file_url（已是直链自动跳过） |
| 3 转写 | asr_transcribe.py | 自动；`--video-id <id>` 单条重试 | transcripts/<id>.md + .raw_asr/ |
| 4 合并 | merge_output.py | 自动；`--force` 重出最新数据 | <博主>/<日期>-<标题>.md + INDEX.md |

三条入口可混用；统一写 `<workspace>/videos.json`（默认 `~/VideoMonitor`），阶段 `collected→parsed→transcribed→merged`，全幂等。

性能与省钱设计：去水印解析默认 3 路并发（`parser.concurrency` 可调 1-4）；`transcript_library` 指向导出线素材库根目录时，转写前先按 aweme_id 复用已有逐字稿（asr.source 会标 `biji-library:*`）；Monid 调用自动记台账 `.cost_log.json`。

## 外部依赖

- **Monid**（api.monid.ai，`monid_live_` key）：工具网关，$0.0012/次
  - `anyapi /douyin.user_posts`：入参 secUserId（博主主页链接 `/user/` 后那串），返回 `output.data.posts[]`（数据齐全，**无直链**，nextCursor 分页）
  - `anyapi /douyin.video`：入参分享链接，返回 `output.data.videoUrl`（无水印直链）+ 全套数据（顺带回填）
  - 余额：https://app.monid.ai/wallet ；BLOCKED = 预算控制/余额问题
- **去水印兜底**（parser.mode=auto）：Monid 失败自动切 `url_template` 配的第三方接口（如 zhuceka/大圣API，直链在 `data.video`，无 .mp4 后缀以 `?mime_type=video_mp4` 结尾——工具已兼容）
- **阿里云百炼 Paraformer**（sk- key）：提交+轮询，**mp4 可直传**，结果 URL 24h 内要取。文档：https://help.aliyun.com/zh/model-studio/paraformer-recorded-speech-recognition-restful-api

## 本地音视频文件转写（无直链时）

Paraformer 只收公网 URL。用 Monid 的免费 sfs 文件系统中转（1GB 免费）：
`/put` 签名上传 → `curl -T` 传文件 → `/cat?ttl=1h` 换公网直链 → 填进 videos.json 的 video_file_url 再跑步骤3。

## 排错

| 现象 | 处理 |
| --- | --- |
| InvalidFile.DownloadFailed | 直链过期/防盗链 → 重跑 parse 立即转写 |
| InvalidApiKey | 百炼 key 填错（要 sk- 开头，不是阿里云 RAM AK） |
| SUCCESS_WITH_NO_VALID_FRAGMENT | 纯 BGM 无人声，正常跳过 |
| Throttling | 稍后重跑（task_id 已存，续轮询不重复计费） |
| zhuceka 解析失败 | 看 videos.json 的 parse_error 字段；换回 Monid 模式 |
| Monid BLOCKED | 工作区预算控制，去 app.monid.ai 调整或充值 |
