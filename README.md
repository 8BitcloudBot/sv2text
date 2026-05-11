# SV2TEXT — 抖音收藏视频智能分析系统

> 自动采集抖音收藏 → AI 智能过滤 → 无水印下载 → Qwen 视觉分析 → 生成求职参考报告

## 项目背景

刷抖音已经成为我获取求职信息和 AI 前沿知识的主要方式。每天通勤、午休、睡前，随手收藏了大量"以后再看"的干货视频——面经、薪资爆料、内推渠道、Agent 开发教程、Claude Code 技巧、RAG 架构解析……但 735 个收藏躺在那里，真正点开看完的不到 10%。

**痛点很明确**：
- 收藏即遗忘，海量视频积压，根本没有时间逐条观看
- 视频信息密度低——10 分钟的视频核心干货往往只有 2 分钟
- 无法快速检索和对比——想找"有哪些外企还在春招"只能一个个翻
- 图文笔记截图模糊，文字难以复用

SV2TEXT 解决的就是这个问题：**让 AI 替你看视频**。它自动爬取你的抖音收藏，用 LLM 过滤出与求职/职场/AI 技术真正相关的内容，直接下载无水印视频，然后调用 Qwen 多模态模型逐帧分析——提取企业名、岗位、薪资、面试题、技术架构、操作步骤等关键信息，最终生成一份可直接查阅的结构化报告。

**适合人群**：
- 正在春招/秋招的应届生，收藏了大量面经和招聘信息来不及整理
- AI/大模型/AIGC 方向的开发者，通过抖音关注技术前沿但缺少系统性梳理
- 有信息囤积习惯的"收藏夹吃灰患者"，希望把碎片化内容转化为可检索的知识库
- 任何想用 AI 自动化处理短视频内容，构建个人知识管理流水线的技术爱好者

简单说：**以前你需要花几十个小时看完的视频，现在花几分钟读一份报告就够了。**

## 功能概览

SV2TEXT 将你的抖音收藏夹转化为结构化的求职参考手册。它全量爬取你的收藏列表，用 AI 过滤出与求职/职场/AI 技术相关的内容，通过抖音 Web API 获取无水印视频直链下载，最后调用 Qwen 多模态模型对视频逐帧分析，提取企业名、岗位、薪资、面试技巧等关键信息。

```
抖音收藏 → 全量采集 → AI过滤 → 无水印下载 → Qwen视觉分析 → Markdown报告
```

## 核心特性

- **全量采集**: 通过抖音 Web API（含 ABogus 反爬签名）分页爬取全部收藏
- **智能过滤**: Qwen 多模态模型基于标题+封面图判断是否与求职/职场/AI相关
- **高速下载**: 优先通过抖音视频详情 API 获取无水印 CDN 直链下载，速度远超浏览器方案
- **图文笔记**: 自动识别图文笔记，提取原始高清图片
- **视频分析**: Qwen 视觉模型逐帧分析，提取结构化信息（企业/岗位/薪资/技巧等）
- **断点续传**: 全流程支持中断恢复，不重复工作
- **分层报告**: 高价值内容优先，按分类汇总，生成 Markdown + JSON 双格式报告

## 系统架构

```
                         config.py
                      (全局配置/路径)
                       /    |    \
                      /     |     \
         fetch_collection  download  filter_collection  analyze.py
         (listcollection)  (详情API  (Qwen过滤)         (Qwen分析)
               |           +直链)        |                  |
               |            |            |                  |
          src/douyin/  ←───┘            └──────────────────┘
          ├── signer.py     (ABogus 签名算法)
          ├── antispam.py   (msToken/ttWid 反爬令牌)
          ├── api.py        (视频详情/图文提取)
          └── __init__.py
```

### 数据流

```
master_videos.csv ──── 全量收藏 (video_id, title, cover_url) ──── 持久化
       │
       ├─ vs ─ processed_videos.csv (已分析标记)
       │
       └──→ session CSV ──→ filter ──→ filtered CSV ──→ download ──→ videos/
                                     │                                  │
                                     └──→ analyze ←────────────────────┘
                                              │
                                              ├── frames/ (ffmpeg 抽帧)
                                              ├── Qwen vision API
                                              ├── reports/individual/{id}.json (断点)
                                              └── reports/analysis_report.md
```

### 下载链路

```
download_video(url)
  │
  ├── extract_aweme_id() → 19位视频ID
  │
  ├── get_video_detail() → GET /aweme/v1/web/aweme/detail/
  │     ├── DouyinAntiSpam (msToken + ttWid + 指纹)
  │     └── ABogus (a_bogus 签名)
  │
  ├── type=video → extract_cdn_url() → HTTP直链下载
  │     └── 按分辨率/FPS/码率排序选最高画质
  │
  ├── type=image_note → extract_note_images() → 逐张下载
  │
  └── 失败 → yt-dlp 回退
```

## 快速开始

### 环境要求

- Python 3.10+
- ffmpeg / ffprobe (视频抽帧)
- yt-dlp (下载回退)
- Chrome/Chromium (Playwright — 仅 cookie 更新用)

### 安装

```bash
# 克隆仓库
git clone https://github.com/你的用户名/sv2text.git
cd sv2text

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器 (可选，用于 cookie 更新)
playwright install chromium
```

### 配置

复制环境变量模板并填入真实信息:

```bash
cp .env.example .env
```

编辑 `.env`:

```env
# 阿里云百炼 API Key（必填）
QWEN_API_KEY=sk-xxxxxxxxxxxxxxxx

# Qwen 模型（推荐 qwen3.5-plus，预算有限可用 qwen3.5-flash）
QWEN_MODEL=qwen3.5-plus

# 阿里云百炼 API 地址
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 抖音 Cookie（必填，从浏览器获取）
DOUYIN_COOKIE=your_long_cookie_string_here

# 分析参数
SCORE_THRESHOLD=3          # 高价值内容最低评分
MAX_CONCURRENCY=3          # API 并发数
MAX_FRAMES=30              # 单视频最大抽帧数
ENABLE_FILTER=true         # 启用 AI 智能过滤
ENABLE_AUDIO=false         # 启用音频分析
```

获取抖音 Cookie:
1. 安装 [EditThisCookie](https://www.editthiscookie.com/) 浏览器扩展
2. 登录抖音网页版 `www.douyin.com`
3. 点击自己的收藏标签页
4. 导出 Cookie 为 JSON，粘贴到 `ttcookie.json`
5. 运行 `python update_cookie.py` 自动更新 `.env`

### 运行

```bash
# 完整流程（采集 + 过滤 + 下载 + 分析）
python run.py

# 仅采集收藏列表
python run.py --step fetch

# 仅处理未处理视频（过滤 → 下载 → 分析）
python run.py --step process

# 增量采集（只获取新增的收藏）
python run.py --step fetch --incremental

# 重新分析已下载视频
python run.py --step process --reanalyze

# 清除临时帧/音频文件
python run.py --clean-frames
```

## 命令行

```
python run.py [OPTIONS]

选项:
  --step {fetch,process,all}   执行步骤 (默认: all)
  --incremental                增量采集模式
  --reanalyze                  重新分析已下载视频
  --clean-frames               清除帧和音频临时文件
```

## 报告输出示例

分析完成后，在 `data/fetch_{session}/reports/analysis_report.md` 查看报告:

```markdown
# 抖音收藏视频分析报告

> 生成时间: 2026-05-11T19:00:00
> 模型: qwen3.5-plus  |  视频: 187 条
> 分析成功: 180  |  失败: 7
> 高价值(>=4分): 45  |  已过滤: 10

## ⭐ 高价值内容（评分 >= 4）

### 1. 字节AI Agent面试经验
- **评分**: ⭐⭐⭐⭐ (4/5)
- **分类**: 面试技巧
- **🏢 企业/机构**: 字节跳动
- **💼 岗位**: AI Agent 工程师
- **🔧 关键技巧**:
  - ReAct 机制在 Agent 中的应用
  - 工具调用上下文污染解决方案
- **📊 关键数据**: 面试3轮，薪资范围 30-50K

### 2. 2026春招免笔试央国企
- **评分**: ⭐⭐⭐⭐⭐ (5/5)
- **分类**: 招聘信息
- **🏢 企业/机构**: 国家能源集团, 中石油, 中国烟草
- **🔗 投递渠道**: https://zhaopin.xxx.com
```

## 项目结构

```
sv2text/
├── run.py                  # CLI 入口，工作流编排
├── config.py               # 全局配置（环境变量、路径、日志）
├── fetch_collection.py     # 抖音收藏采集（listcollection API）
├── filter_collection.py    # AI 智能过滤（Qwen 多模态）
├── download.py             # 视频下载（API 直链 + yt-dlp 回退）
├── analyze.py              # AI 分析核心（抽帧 + Qwen 视觉）
├── update_cookie.py        # Cookie 更新工具
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量模板
├── .gitignore
│
├── src/
│   └── douyin/
│       ├── __init__.py     # 模块导出
│       ├── signer.py       # ABogus 签名算法
│       ├── antispam.py     # 反爬令牌（msToken/ttWid/指纹）
│       └── api.py          # 视频详情 API 封装
│
├── tests/
│   ├── conftest.py         # 共享 fixtures
│   ├── test_run.py         # CLI 编排测试
│   ├── test_config.py      # 配置验证测试
│   ├── test_fetch.py       # 收藏采集测试
│   ├── test_filter.py      # 智能过滤测试
│   ├── test_download.py    # 下载模块测试
│   ├── test_analyze.py     # 分析模块测试
│   └── test_api.py         # API 模块测试
│
├── data/                   # 自动生成 (gitignored)
│   ├── master_videos.csv   # 全量收藏列表
│   ├── processed_videos.csv # 已处理记录
│   └── fetch_{session}/    # Session 工作目录
│       ├── fetch_{session}.csv
│       ├── filtered_{session}.csv
│       ├── videos/
│       └── reports/
│
├── logs/                   # 日志文件 (gitignored)
├── frames/                 # 临时帧文件 (gitignored)
└── audio/                  # 临时音频文件 (gitignored)
```

## 开发

```bash
# 安装开发依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/ -v

# 测试覆盖率
python -m pytest tests/ -v
# 100 个测试用例，覆盖所有核心模块
```

### 测试结构

| 模块 | 测试文件 | 用例数 | 覆盖内容 |
|------|----------|--------|----------|
| 配置 | `test_config.py` | 7 | 参数验证、日志初始化 |
| 采集 | `test_fetch.py` | 8 | API 调用、去重、增量追加 |
| 过滤 | `test_filter.py` | 16 | CSV解析、Qwen调用、断点 |
| 下载 | `test_download.py` | 11 | URL读取、视频校验、下载策略 |
| 分析 | `test_analyze.py` | 30 | JSON解析、抽帧、API调用、报告生成 |
| API | `test_api.py` | 25 | 视频详情、CDN提取、图文识别 |
| 编排 | `test_run.py` | 8 | CLI参数、步骤串联、异常处理 |

## 技术细节

### ABogus 签名

项目实现了完整的 ABogus 签名算法（适配自 [TikTokDownloader](https://github.com/JoeanAmier/TikTokDownloader)），使用 SM3 哈希 + RC4 加密，确保 API 请求不会被抖音反爬系统拦截。

### 反爬策略

- **msToken**: 向字节跳动 MSSDK 动态获取令牌
- **ttWid**: 注册设备标识符
- **浏览器指纹**: 模拟完整浏览器环境参数
- **Cookie 组合**: 基础 cookie + msToken + ttWid

### 无水印下载

通过 `/aweme/v1/web/aweme/detail/` Web API 获取视频详情，直接从 `bit_rate` 列表中提取 CDN 地址。Web 端返回的地址天然无水印，无需额外处理。

### 视频分析

- **自适应抽帧**: ≤60s 视频每3秒1帧，≤180s 每5秒1帧，>180s 每10秒1帧
- **音频转录**: 可选启用，通过 Qwen omni 模型将语音转文字作为分析补充
- **结构化输出**: JSON Schema 约束，提取 10+ 维度信息

## 依赖

```
openai>=1.30.0          # Qwen API 调用
yt-dlp>=2024.12.0       # 视频下载回退
requests>=2.31.0        # HTTP 请求
python-dotenv>=1.0.0    # 环境变量加载
tqdm>=4.66.0            # 进度条
pytest>=9.0.0           # 测试框架
pytest-mock>=3.15.0     # Mock 工具
gmssl>=3.2.2            # 国密 SM3 哈希
playwright>=1.50.0      # Cookie 更新
```

## 参考项目

- [TikTokDownloader](https://github.com/JoeanAmier/TikTokDownloader) — 抖音数据采集，ABogus 签名参考
- [f2](https://github.com/Johnserf-Seed/f2) — 多平台高速下载器，API 设计参考

## License

MIT
