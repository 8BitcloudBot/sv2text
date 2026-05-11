#!/usr/bin/env python3
"""
SV2TEXT — 一键运行入口
新流程: 全量采集 → 对比未处理 → 过滤 → 下载 → 分析 → 标记已处理
"""

import sys
import csv
import shutil
import logging
import argparse
from pathlib import Path
from config import (
    setup_logging, validate, init_session,
    PROJECT_ROOT, FRAME_DIR, AUDIO_DIR,
    ENABLE_FILTER, MASTER_CSV, PROCESSED_CSV,
    get_video_dir, get_report_dir, get_checkpoint_dir,
    get_csv_file, get_filtered_csv_file, get_filter_checkpoint,
)

logger = setup_logging("run")


def _clean_temp_files():
    for d, label in [(FRAME_DIR, "帧"), (AUDIO_DIR, "音频")]:
        if d.exists():
            try:
                shutil.rmtree(d)
                d.mkdir(parents=True, exist_ok=True)
                logger.info(f"已清理 {label} 目录")
            except OSError as e:
                logger.warning(f"清理失败: {e}")


def _read_csv_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        return {row[0] for row in reader if row}


def _read_csv(path: Path) -> list[tuple[str, str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        return [(row[0], row[1], row[2] if len(row) > 2 else "") for row in reader if len(row) >= 2]


def _mark_processed(video_id: str, title: str):
    write_header = not PROCESSED_CSV.exists()
    with open(PROCESSED_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["video_id", "title"])
        writer.writerow([video_id, title])


# ─── 步骤 1: 全量采集 ───────────────────────────────────────────────
def step_fetch(incremental: bool = False):
    from fetch_collection import fetch_all
    validate("fetch")
    logger.info("=" * 50)
    logger.info("步骤 1: 全量获取收藏 → master_videos.csv")
    logger.info("=" * 50)
    fetch_all(incremental=incremental)


# ─── 步骤 2: 智能过滤 ───────────────────────────────────────────────
def step_filter(incremental: bool = False):
    from filter_collection import filter_all
    validate("filter")
    logger.info("=" * 50)
    logger.info("步骤 2: 智能过滤")
    logger.info("=" * 50)
    filter_all(incremental=incremental)


# ─── 步骤 3: 下载 ───────────────────────────────────────────────────
def step_download():
    from download import download_all
    logger.info("=" * 50)
    logger.info("步骤 3: 下载视频")
    logger.info("=" * 50)
    download_all()


# ─── 步骤 4: 分析 + 标记已处理 ──────────────────────────────────────
def step_analyze(reanalyze: bool = False):
    from analyze import analyze_all
    validate("analyze")
    logger.info("=" * 50)
    logger.info("步骤 4: AI 分析 + 标记已处理")
    logger.info("=" * 50)
    success = analyze_all(reanalyze=reanalyze)

    # 分析完成后，标记成功分析的视频为已处理
    processed_ids = _read_csv_ids(PROCESSED_CSV)
    checkpoint_dir = get_checkpoint_dir()
    if checkpoint_dir.exists():
        new_count = 0
        for checkpoint_file in sorted(checkpoint_dir.glob("*.json")):
            import json
            try:
                data = json.loads(checkpoint_file.read_text())
                vid = data.get("video_id", "")
                if vid and vid not in processed_ids and "error" not in data:
                    # 从 master CSV 找标题
                    title = ""
                    for mid, mtitle in _read_csv(MASTER_CSV):
                        if mid == vid:
                            title = mtitle
                            break
                    _mark_processed(vid, title or data.get("title", vid))
                    new_count += 1
            except (json.JSONDecodeError, IOError):
                pass
        if new_count:
            logger.info(f"已标记 {new_count} 条为已处理 → {PROCESSED_CSV}")

    return success


# ─── 核心: 发现未处理视频并串联处理 ─────────────────────────────────
def _sync_unprocessed():
    """对比 master CSV 和 processed CSV，将未处理的写入 session CSV 供后续步骤使用"""
    master = _read_csv(MASTER_CSV)
    processed_ids = _read_csv_ids(PROCESSED_CSV)

    unprocessed = [(vid, title, cover) for vid, title, cover in master if vid not in processed_ids]

    logger.info(f"master: {len(master)} 条  |  processed: {len(processed_ids)} 条  |  未处理: {len(unprocessed)} 条")

    if not unprocessed:
        logger.info("所有视频已处理完毕！")
        return 0

    # 写入 session CSV（含 URL，供 filter/download 使用）
    session_csv = get_csv_file()
    with open(session_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["video_id", "title", "url", "cover_url"])
        for vid, title, cover_url in unprocessed:
            writer.writerow([vid, title, f"https://www.douyin.com/video/{vid}", cover_url])

    return len(unprocessed)


# ─── CLI 入口 ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="SV2TEXT — 抖音收藏视频智能分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run.py                        # fetch + 处理所有未处理视频
  python run.py --step fetch           # 仅全量采集
  python run.py --step process         # 仅处理未处理视频
  python run.py --reanalyze            # 重新分析已下载视频
  python run.py --step fetch --incremental  # 增量采集
""",
    )
    parser.add_argument(
        "--step", choices=["fetch", "process", "all"],
        default="all", help="指定步骤（默认: all）"
    )
    parser.add_argument("--incremental", action="store_true", help="增量采集模式")
    parser.add_argument("--reanalyze", action="store_true", help="重新分析已下载视频")
    parser.add_argument("--clean-frames", action="store_true", help="清除临时文件")

    args = parser.parse_args()
    ts = init_session()
    logger.info(f"Session: {ts}")

    try:
        if args.clean_frames:
            _clean_temp_files()

        if args.step in ("fetch", "all"):
            step_fetch(incremental=args.incremental)

        if args.step in ("process", "all"):
            count = _sync_unprocessed()
            if count > 0:
                if ENABLE_FILTER:
                    step_filter()
                step_download()
                step_analyze(reanalyze=args.reanalyze)
            else:
                logger.info("无未处理视频，跳过 process 步骤")

        logger.info("=" * 50)
        logger.info(f"完成！报告: {get_report_dir() / 'analysis_report.md'}")
        logger.info(f"已处理记录: {PROCESSED_CSV}")
        logger.info("=" * 50)

    except RuntimeError as e:
        logger.error(f"运行失败: {e}")
        logger.info("请检查 .env 配置")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("用户中断")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"未预期的错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
