"""
抖音视频详情 API 模块
调用 /aweme/v1/web/aweme/detail/ 获取无水印 CDN 地址和图文图片。

参考: TikTokDownloader (JoeanAmier) 和 f2 (Johnserf-Seed)
"""

import requests
from urllib.parse import urlencode
from config import DOUYIN_COOKIE, DOUYIN_USER_AGENT, setup_logging
from src.douyin import ABogus, DouyinAntiSpam

logger = setup_logging("api")

DETAIL_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

_anti_spam: DouyinAntiSpam | None = None


def _get_anti_spam() -> DouyinAntiSpam:
    global _anti_spam
    if _anti_spam is None:
        _anti_spam = DouyinAntiSpam(DOUYIN_USER_AGENT)
    return _anti_spam


def get_video_detail(aweme_id: str) -> dict | None:
    """
    调用抖音视频详情 API，返回原始响应 JSON。
    成功时返回完整响应，失败返回 None。
    """
    anti = _get_anti_spam()
    cookie = anti.get_cookie_string(DOUYIN_COOKIE)

    params = anti.get_fingerprint_params()
    params.update({
        "aweme_id": aweme_id,
        "version_code": "190500",
        "version_name": "19.5.0",
    })

    abogus = ABogus(DOUYIN_USER_AGENT, "MacIntel")
    params["a_bogus"] = abogus.get_value(params, "GET")

    url = f"{DETAIL_URL}?{urlencode(params)}"

    headers = {
        "User-Agent": DOUYIN_USER_AGENT,
        "Cookie": cookie,
        "Referer": "https://www.douyin.com/?recommend=1",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug(f"  视频详情 API 请求失败 (aweme_id={aweme_id}): {e}")
        return None


def extract_cdn_url(detail: dict) -> str | None:
    """
    从视频详情响应中提取最高画质的无水印 CDN URL。
    遍历 bit_rate 列表，按分辨率+FPS+码率排序取最高。
    """
    try:
        bit_rate = detail.get("aweme_detail", {}).get("video", {}).get("bit_rate")
        if not bit_rate:
            return None

        scored = []
        for entry in bit_rate:
            addr = entry.get("play_addr", {}).get("url_list", [])
            if not addr:
                continue
            height = entry.get("play_addr", {}).get("height", 0)
            width = entry.get("play_addr", {}).get("width", 0)
            fps = entry.get("FPS", 0)
            br = entry.get("bit_rate", 0)
            size = entry.get("play_addr", {}).get("data_size", 0)
            # 按 max(h,w), fps, bitrate, size 排序
            scored.append((max(height, width), fps, br, size, addr[0]))

        if not scored:
            return None

        scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        return scored[-1][4]  # 最高画质的 URL
    except (KeyError, TypeError, IndexError):
        return None


def extract_note_images(detail: dict) -> list[str]:
    """
    从图文笔记响应中提取原始图片 URL 列表。
    返回 list[str]，无图片时返回空列表。
    """
    try:
        images = detail.get("aweme_detail", {}).get("images")
        if not images:
            return []
        result = []
        for img in images:
            url_list = img.get("url_list", [])
            if url_list:
                result.append(url_list[0])
        return result
    except (KeyError, TypeError):
        return []


def is_image_note(detail: dict) -> bool:
    """判断响应是否为图文笔记（无 video 但有 images）"""
    has_video = bool(
        detail.get("aweme_detail", {})
        .get("video", {})
        .get("bit_rate")
    )
    has_images = bool(
        detail.get("aweme_detail", {})
        .get("images")
    )
    return not has_video and has_images


def extract_aweme_id(url: str) -> str | None:
    """从抖音视频 URL 中提取 aweme_id"""
    import re
    if "douyin.com" not in url:
        return None
    match = re.search(r'/video/(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/note/(\d+)', url)
    if match:
        return match.group(1)
    return None


def get_download_info(url: str) -> dict:
    """
    一站式获取下载信息。
    返回 dict:
    {
        "type": "video" | "image_note" | "error",
        "cdn_url": str | None,       # 视频 CDN URL
        "image_urls": list[str],     # 图文笔记图片 URL
        "detail": dict | None,       # 原始 API 响应
        "error": str | None,         # 错误信息
    }
    """
    result = {
        "type": "error",
        "cdn_url": None,
        "image_urls": [],
        "detail": None,
        "error": None,
    }

    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        result["error"] = f"无法从 URL 提取视频 ID: {url}"
        return result

    detail = get_video_detail(aweme_id)
    if not detail:
        result["error"] = f"API 请求失败: aweme_id={aweme_id}"
        return result

    result["detail"] = detail

    # 检查状态码
    status = detail.get("status_code", 0)
    if status != 0:
        result["error"] = f"API 返回错误状态: {status}"
        return result

    if is_image_note(detail):
        image_urls = extract_note_images(detail)
        if image_urls:
            result["type"] = "image_note"
            result["image_urls"] = image_urls
        else:
            result["error"] = "图文笔记无图片"
        return result

    cdn_url = extract_cdn_url(detail)
    if cdn_url:
        result["type"] = "video"
        result["cdn_url"] = cdn_url
    else:
        result["error"] = "无法提取视频下载地址（bit_rate 为空或无 url_list）"

    return result
