# 内容采集方法论（用户需求 → 实现方式提醒）

用户带着某种内容来源的需求来时，按此表提醒实现方式。两条已建流水线见文末。

| 内容类型 | 实现方式 |
| --- | --- |
| 公众号文章 | Obsidian 剪藏插件 → x 文章 / y youtube 视频逐字稿 |
| 有链接的视频（抖音/B站/小宇宙/小红书） | 手动"得到大脑"（粘贴链接 → 逐字稿+AI摘要）→ 抖音支持导出一个博主全部的逐字稿并订阅 |
| 没链接的音视频（下载文件、自录） | 通义听悟（手动上传文件转写）/ 阿里云的音频转文字 |
| 图片（小红书图文等） | 下载/截图 → 拖给多模态提取 |
| 作品数据（点赞/评论数） | 社媒助手（Chrome 插件 xisence，达人主页批量导出 Excel）→ social_stats.py 解析 → 和得到大脑导出的逐字稿合并 |
| 评论区 | 乌云踏雪 skill：https://github.com/Pluviobyte/douyin-comments（已安装于 ~/.claude/skills/douyin-comments，需 Claude in Chrome + 已登录抖音） |
| 聊天记录（私域） | 手动微信多选合并转发 → 直接发 WorkBuddy |
| 朋友圈 | 手动截图或下载 → 多模态提取（暂无批量方案） |
| 直播回放 | 闲鱼代抓 / 会员订阅导出 → 听悟转写 |
| 盯状态（持续监控） | TikHub / Monid（二选一，当前选型 Monid） |

## 快速导出流水线（已实现：content-export skill）

得到大脑订阅 → skill 批量导出 → 社媒助手导出数据 → 文案和数据合并
配上乌云踏雪的 skill 导出评论区

> 状态：skill 位于 ~/.claude/skills/content-export。得到大脑=Get笔记（biji.com），biji_export.py 批量导出（token 自动刷新+增量）；社媒助手=Chrome 插件（xisence），用户在达人主页手动批量导出 Excel，social_stats.py 自动解析列名；merge_export.py 按标题归一化匹配合并。首次使用需 playwright + login 一次。

## 快速监控流水线（已实现：video-monitor skill）

Monid 采集视频简要信息（核心是数据和视频链接）→ 去水印 API 解析视频文件直链（如果直接能采集到视频文件链接就跳过这一步）→ 阿里云音频转文字提取逐字稿 → 将内容和数据合并

> 状态：skill 位于 ~/.claude/skills/video-monitor。待补：Monid API 文档（填 config 的 monid 段）、去水印接口地址（填 parser 段）、DashScope API Key。
