"""
SV2TEXT — 视频下载模块
优先通过抖音 Web API 获取无水印 CDN 地址直链下载，
失败时回退到 yt-dlp。
"""

import re
import csv
import time
import tempfile
import subprocess
import requests
from pathlib import Path
from config import (
    DOUYIN_COOKIE, DOUYIN_USER_AGENT,
    get_csv_file, get_filtered_csv_file, get_video_dir,
    setup_logging,
)
from src.douyin import get_download_info

logger = setup_logging("download")


# ─── URL 读取 ────────────────────────────────────────────────────────

def _read_urls() -> list[tuple[str, str, str]]:
    filtered = get_filtered_csv_file()
    source = filtered if filtered.exists() else get_csv_file()
    if not source.exists():
        raise FileNotFoundError(f"{source.name} 不存在，请先运行 fetch/filter")
    entries = []
    with open(source, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 3:
                entries.append((row[0], row[1], row[2]))
    return entries


# ─── 视频校验 ────────────────────────────────────────────────────────

def verify_video(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        return float(result.stdout.strip()) > 1.0
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return path.exists() and path.stat().st_size > 10240


# ─── 下载 ────────────────────────────────────────────────────────────

def download_video(video_id: str, url: str, title: str) -> bool:
    """下载视频/图文：优先 API 获取 CDN 地址直链下载，失败回退 yt-dlp"""
    safe_title = re.sub(r'[\\/:*?"<>|]', '', title[:20]).strip()
    video_dir = get_video_dir()

    if "douyin.com" not in url:
        logger.info(f"  跳过非抖音链接: {url[:50]}")
        return False

    info = get_download_info(url)

    if info["type"] == "video" and info["cdn_url"]:
        out_path = video_dir / f"{video_id}_{safe_title}.mp4"
        if _download_from_url(info["cdn_url"], out_path):
            return True
        # CDN 直链下载失败，回退 yt-dlp
        return _download_via_ytdlp(video_id, url, out_path)

    if info["type"] == "image_note" and info["image_urls"]:
        note_dir = video_dir / f"note_{video_id}"
        note_dir.mkdir(parents=True, exist_ok=True)
        count = _download_images(info["image_urls"], note_dir)
        if count > 0:
            logger.info(f"  图文笔记已下载 {count} 张原始图片")
            return True
        logger.info("  图文笔记下载失败，无图片")
        return False

    error = info.get("error", "未知错误")
    logger.info(f"  API 获取失败: {error}")

    # 最后回退 yt-dlp
    out_path = video_dir / f"{video_id}_{safe_title}.mp4"
    return _download_via_ytdlp(video_id, url, out_path)


def _download_images(image_urls: list[str], output_dir: Path) -> int:
    """HTTP 下载图片列表到指定目录"""
    count = 0
    for i, img_url in enumerate(image_urls):
        try:
            resp = requests.get(
                img_url,
                headers={"User-Agent": DOUYIN_USER_AGENT, "Referer": "https://www.douyin.com/"},
                timeout=60,
            )
            resp.raise_for_status()
            ext = ".jpg"
            content_type = resp.headers.get("content-type", "")
            if "webp" in content_type:
                ext = ".webp"
            elif "png" in content_type:
                ext = ".png"
            path = output_dir / f"{i:04d}{ext}"
            path.write_bytes(resp.content)
            count += 1
        except Exception as e:
            logger.debug(f"  图片下载失败 [{i}]: {e}")
    return count


def _download_from_url(cdn_url: str, out_path: Path) -> bool:
    """直接 HTTP 下载 CDN URL"""
    headers = {
        "User-Agent": DOUYIN_USER_AGENT,
        "Referer": "https://www.douyin.com/",
    }
    try:
        start = time.time()
        resp = requests.get(cdn_url, headers=headers, stream=True, timeout=120)
        resp.raise_for_status()
        total = 0
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                total += len(chunk)
        elapsed = time.time() - start

        if verify_video(out_path):
            logger.info(f"  下载完成 {total / 1024 / 1024:.1f}MB ({elapsed:.1f}s)")
            return True
        else:
            logger.warning(f"  校验失败，删除: {out_path.name}")
            try:
                out_path.unlink()
            except OSError:
                pass
            return False
    except Exception as e:
        logger.debug(f"  直链下载失败: {e}")
        return False


def _download_via_ytdlp(video_id: str, url: str, out_path: Path) -> bool:
    """yt-dlp 回退方案"""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir=Path(__file__).parent
    )
    tmp.write("# Netscape HTTP Cookie File\n")
    for item in DOUYIN_COOKIE.split("; "):
        if "=" in item:
            name, value = item.split("=", 1)
            tmp.write(f".douyin.com\tTRUE\t/\tFALSE\t0\t{name}\t{value}\n")
    tmp.close()
    cookie_path = Path(tmp.name)

    cmd = [
        "yt-dlp",
        "--cookies", str(cookie_path),
        "--add-header", f"User-Agent:{DOUYIN_USER_AGENT}",
        "--add-header", "Referer:https://www.douyin.com/",
        "--format", "best[height<=720]",
        "--output", str(out_path.parent / f"{video_id}.%(ext)s"),
        "--no-overwrites", "--socket-timeout", "30",
        "--retries", "3", "--quiet", url,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or b"").decode(errors="replace")[-300:]
        if "Fresh cookies" in err_msg:
            logger.warning("  抖音视频详情 API 被反爬拦截")
        else:
            logger.warning(f"  yt-dlp 错误: {err_msg[-200:]}")
        _cleanup(cookie_path)
        return False
    except subprocess.TimeoutExpired:
        logger.warning("  下载超时")
        _cleanup(cookie_path)
        return False

    _cleanup(cookie_path)

    for f in out_path.parent.glob(f"{video_id}*"):
        if verify_video(f):
            logger.info(f"  下载完成 ({f.stat().st_size / 1024 / 1024:.1f}MB)")
            return True
        else:
            logger.warning(f"  校验失败: {f.name}")
            try:
                f.unlink()
            except OSError:
                pass
    return False


def _cleanup(p: Path):
    try:
        p.unlink()
    except OSError:
        pass


# ─── 批量下载 ────────────────────────────────────────────────────────

def download_all() -> int:
    logger.info("===== 开始下载视频 =====")
    entries = _read_urls()
    logger.info(f"共 {len(entries)} 条 URL 待处理")
    video_dir = get_video_dir()

    success = skipped = failed = 0
    for i, (vid, title, url) in enumerate(entries, 1):
        if list(video_dir.glob(f"{vid}_*")):
            logger.info(f"[{i}/{len(entries)}] 跳过: {title[:30]}...")
            skipped += 1
            continue

        logger.info(f"[{i}/{len(entries)}] 下载: {title[:30]}...")
        if download_video(vid, url, title):
            success += 1
        else:
            logger.warning(f"  下载失败: {vid}")
            failed += 1

    logger.info(f"===== 下载完成: 成功 {success}, 跳过 {skipped}, 失败 {failed} =====")

    if failed > 0 and success == 0:
        _show_manual_guide(entries)

    return success


def _show_manual_guide(entries):
    logger.info("")
    logger.info("所有自动下载均失败。请手动下载：")
    logger.info(f"   存放目录: {get_video_dir()}")
    logger.info("   文件名格式: {video_id}_{标题}.mp4")
    for vid, title, url in entries[:10]:
        logger.info(f"     {title[:30]:<32} -> {url}")
    if len(entries) > 10:
        logger.info(f"     ... 还有 {len(entries) - 10} 条")


if __name__ == "__main__":
    download_all()
