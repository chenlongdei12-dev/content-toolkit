# 导出流水线详解（Get笔记 → 社媒助手 → 合并）

```
Get笔记订阅 → biji批量导出 → 社媒助手导数据 → 文案和数据合并
(用户订阅)   biji_export.py   shejiao_export.py   merge_export.py
             (token自动刷新)  / social_stats.py
```

## Get笔记（得到大脑）逐字稿导出 — biji_export.py

一次性设置：
```bash
pip3 install --user playwright && python3 -m playwright install chromium
python3 biji_export.py login        # 开浏览器扫码，一次即可，之后 token 自动无头刷新
```

命令：`topics`（列知识库）→ `follows <alias>`（列博主拿 url）→ `export "<url>"`（增量导出）→ `status "<url>"`（续传建议）。全部输出单行 JSON。`run.py export-biji "名字"` 自动串起来。

- API：`knowledge-api.trytalks.com`，`{h,c}` 包裹（数据在 c），JWT 30 分钟自动刷新
- 凭据：`~/.biji_exporter/skill_credentials.json`；登录态：`~/.biji_exporter/browser_data_skill`
- 增量：文件名 `{序号}_{post_id}_{标题}.md`，post_id 去重；每篇带 `> 链接：` 抖音源链 + 目录下 links.json
- 速度：约 3 篇/秒，712 篇全量约 6 分钟
- 代理报错 → 关 Clash/Surge 或 `BIJI_USE_SYSTEM_PROXY=1`

## 社媒助手作品数据

**自动（shejiao_export.py）**：需要专用 Chrome 实例（一次性搭建）：
```bash
open -na "Google Chrome" --args --user-data-dir="$HOME/.shejiao_automation" \
  --remote-debugging-port=9222 --no-first-run --no-default-browser-check
# 在该实例里：装社媒助手插件(chromewebstore 搜「社媒助手」) + 登录抖音 + 登录插件账号
```
然后 `python3 run.py export-data "<达人主页URL>"` → 自动点插件面板「导出视频」→ 等采集 → 出 `~/Downloads/{达人}_作品数据_日期.xlsx`。

**手动**：Chrome 装社媒助手插件 → 达人主页 → 批量导出视频数据（Excel）→ 告诉 agent 文件位置。字段建议勾：标题、发布时间、点赞、评论、收藏、转发、视频链接。

## 数据解析与合并

- social_stats.py：xlsx/csv → 统一 JSON。纯标准库读 xlsx；列名自动识别（真实文件已校准：视频描述/视频链接/点赞量/收藏量/评论量/分享量/发布时间/达人昵称）；`1.2万` 等中文数字自动换算
- merge_export.py：**链接视频ID精确匹配**（逐字稿 md 里的 douyin 链接 ↔ 数据表视频链接，同视频多稿共享）→ 标题归一化精确 → 相似度 ≥0.75 → 包含关系；匹配不到的如实标 ❌ 并列在 INDEX 尾部。实测姜Dora：链接匹配 91/110，剩 19 条全是真删稿

## 排错

| 现象 | 处理 |
| --- | --- |
| not_logged_in / 403 反复 | `biji_export.py login`（人在场） |
| topics 全挂 | 平台改版，抓包校准 API 路径 |
| 「导出视频」按钮找不到 | 专用实例没开/插件没登录 → 打开实例手动检查一次 |
| 采集超时 | 重跑（插件有历史记录可续采） |
| 空稿 skip_empty | 该篇无逐字稿（图文物等），正常 |
| 匹配率低 | 看未匹配清单，必要时调 merge_export.py 阈值或补 social_stats.py 列名 |

## 评论区（选配）

抖音单条视频评论深抓用第三方 skill [douyin-comments](https://github.com/Pluviobyte/douyin-comments)（乌云踏雪，需 Chrome 内已登录抖音）；批量评论可用社媒助手自带「批量评论导出」。
