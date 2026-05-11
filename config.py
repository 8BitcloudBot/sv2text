"""
SV2TEXT — 全局配置模块
从 .env 加载所有配置，提供默认值，验证必需项。
"""

import os
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env")

# ─── 会话时间戳 ─────────────────────────────────────────────────────
def session_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M")

# ─── 阿里云百炼 Qwen API ────────────────────────────────────────────
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen3.5-plus")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# ─── 模型自动切换顺序（用量耗尽时按此顺序 fallback） ─────────────────
QWEN_MODEL_FALLBACKS = [
    "qwen3.5-plus",
    "qwen3.5-omni-plus-2026-03-15",
    "qwen3.5-omni-flash-realtime-2026-03-15",
    "qwen3.5-omni-plus-realtime",
]

# ─── 抖音 ───────────────────────────────────────────────────────────
DOUYIN_COOKIE = os.getenv("DOUYIN_COOKIE", "")
DOUYIN_COLLECTION_API = "https://www.douyin.com/aweme/v1/web/aweme/listcollection/"
DOUYIN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ─── 音频分析 ───────────────────────────────────────────────────────
ENABLE_AUDIO = os.getenv("ENABLE_AUDIO", "").lower() == "true"

# ─── 下载前过滤 ─────────────────────────────────────────────────────
ENABLE_FILTER = os.getenv("ENABLE_FILTER", "true").lower() == "true"

# ─── 分析参数 ───────────────────────────────────────────────────────
SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "3"))
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "3"))
MAX_FRAMES = int(os.getenv("MAX_FRAMES", "30"))
REQUEST_INTERVAL = float(os.getenv("REQUEST_INTERVAL", "2.5"))

# ─── API 重试 ───────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2

# ─── 路径（基础） ───────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
FRAME_DIR = PROJECT_ROOT / "frames"
AUDIO_DIR = PROJECT_ROOT / "audio"

# 长期维护的 CSV（不受 session 影响）
MASTER_CSV = DATA_DIR / "master_videos.csv"
PROCESSED_CSV = DATA_DIR / "processed_videos.csv"

# ─── 初始化 session 时间戳 ──────────────────────────────────────────
SESSION_TS: str = ""


def init_session() -> str:
    """在每次运行时调用，生成或复用 session 时间戳并创建目录"""
    global SESSION_TS

    # 复用 30 分钟内的 session
    session_file = DATA_DIR / "current_session.txt"
    if not SESSION_TS:
        if session_file.exists():
            try:
                saved = session_file.read_text().strip()
                saved_time = datetime.strptime(saved, "%Y-%m-%d_%H%M")
                if (datetime.now() - saved_time).total_seconds() < 1800:  # 30 分钟
                    SESSION_TS = saved
            except (ValueError, OSError):
                pass

    SESSION_TS = SESSION_TS or session_ts()
    session_file.write_text(SESSION_TS)

    _ts = SESSION_TS
    for d in [
        DATA_DIR,
        LOG_DIR,
        FRAME_DIR,
        AUDIO_DIR,
        get_video_dir(),
        get_report_dir(),
        get_checkpoint_dir(),
    ]:
        d.mkdir(parents=True, exist_ok=True)
    return SESSION_TS


def session_path(sub: str) -> Path:
    """返回当前 session 下的路径"""
    return DATA_DIR / f"fetch_{SESSION_TS}" / sub


def get_csv_file() -> Path:
    return DATA_DIR / f"fetch_{SESSION_TS}.csv"


def get_filtered_csv_file() -> Path:
    return DATA_DIR / f"filtered_{SESSION_TS}.csv"


def get_video_dir() -> Path:
    return session_path("videos")


def get_report_dir() -> Path:
    return session_path("reports")


def get_checkpoint_dir() -> Path:
    return get_report_dir() / "individual"


def get_filter_checkpoint() -> Path:
    return DATA_DIR / f"filter_checkpoint_{SESSION_TS}.json"


def get_fetch_checkpoint() -> Path:
    return DATA_DIR / f"fetch_checkpoint_{SESSION_TS}.json"


# 确保基础目录存在
for d in [DATA_DIR, LOG_DIR, FRAME_DIR, AUDIO_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def validate(step: str) -> None:
    """验证当前步骤所需的配置是否齐全"""
    if step in ("fetch", "all"):
        if not DOUYIN_COOKIE:
            raise RuntimeError("缺少 DOUYIN_COOKIE，请在 .env 中配置")
    if step in ("download", "all"):
        csv_file = get_filtered_csv_file()
        csv_source = csv_file if csv_file.exists() else get_csv_file()
        video_dir = get_video_dir()
        if not csv_source.exists() and not (video_dir.exists() and list(video_dir.glob("*"))):
            raise RuntimeError(
                "CSV 数据文件不存在且 videos/ 为空，请先运行 fetch"
            )
    if step in ("filter", "all"):
        if not QWEN_API_KEY:
            raise RuntimeError("缺少 QWEN_API_KEY，过滤功能需要 Qwen API")
        if not get_csv_file().exists():
            raise RuntimeError(
                "CSV 数据文件不存在，请先运行: python run.py --step fetch"
            )
    if step in ("analyze", "all"):
        if not QWEN_API_KEY:
            raise RuntimeError("缺少 QWEN_API_KEY，请在 .env 中配置")


def setup_logging(name: str) -> logging.Logger:
    """创建同时输出到文件和终端的 logger"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_filename = f"{name}_{datetime.now().strftime('%Y-%m-%d')}.log"
    fh = logging.FileHandler(LOG_DIR / log_filename, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger
