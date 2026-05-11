"""
SV2TEXT — 抖音收藏获取模块
全量爬取收藏夹视频 → master_videos.csv (listcollection API, count=10, per-page a_bogus)
"""

import csv, time, json, requests
from urllib.parse import urlencode
from config import (
    DOUYIN_COOKIE, DOUYIN_USER_AGENT,
    MASTER_CSV, setup_logging,
)
from src.douyin import ABogus, DouyinAntiSpam

logger = setup_logging("fetch")

COLLECTION_API = "https://www.douyin.com/aweme/v1/web/aweme/listcollection/"
PAGE_SIZE = 10

_anti_spam: DouyinAntiSpam | None = None


def _get_anti_spam() -> DouyinAntiSpam:
    global _anti_spam
    if _anti_spam is None:
        _anti_spam = DouyinAntiSpam(DOUYIN_USER_AGENT)
    return _anti_spam


def fetch_page(cursor: int = 0) -> dict:
    anti = _get_anti_spam()
    cookie = anti.get_cookie_string(DOUYIN_COOKIE)

    # Per-page a_bogus signature
    base_params = anti.get_fingerprint_params()
    abogus = ABogus(DOUYIN_USER_AGENT, "MacIntel")
    base_params["a_bogus"] = abogus.get_value(base_params, "POST")
    url = f"{COLLECTION_API}?{urlencode(base_params)}"

    headers = {
        "User-Agent": DOUYIN_USER_AGENT,
        "Cookie": cookie,
        "Referer": "https://www.douyin.com/user/self?showTab=favorite_collection",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    resp = requests.post(url, data=f"count={PAGE_SIZE}&cursor={cursor}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _load_existing_ids() -> set:
    ids = set()
    if MASTER_CSV.exists():
        with open(MASTER_CSV, encoding="utf-8", newline="") as f:
            next(csv.reader(f), None)
            for row in csv.reader(f):
                if row: ids.add(row[0])
    return ids


def fetch_all(incremental: bool = False):
    logger.info(f"===== 全量获取收藏夹视频 (listcollection, count={PAGE_SIZE}) =====")

    existing_ids = _load_existing_ids()
    if existing_ids:
        logger.info(f"已有 {len(existing_ids)} 条，增量追加")

    seen = set(existing_ids)
    entries = []
    cursor = 0
    page = 0

    while True:
        page += 1
        try:
            data = fetch_page(cursor=cursor)
        except Exception as e:
            logger.error(f"第 {page} 页失败: {e}")
            break

        aweme = data.get("aweme_list") or []
        has_more = data.get("has_more", 0) == 1
        new_cursor = data.get("cursor", 0)

        n = 0
        for item in aweme:
            vid = item.get("aweme_id", "")
            if vid in seen:
                continue
            seen.add(vid)
            desc = item.get("desc", "无标题").replace("\n", " ").replace("\r", "")
            # 提取封面 URL
            video = item.get("video", {})
            cover_info = video.get("cover", {}) or video.get("origin_cover", {})
            cover_url = ""
            if cover_info:
                url_list = cover_info.get("url_list", [])
                cover_url = url_list[0] if url_list else ""
            entries.append((vid, desc, cover_url))
            n += 1

        logger.info(f"P{page}: +{n} ={len(entries)} cursor={new_cursor}")

        if n == 0 or not has_more:
            if n == 0:
                logger.info("无新数据，停止")
            else:
                logger.info("has_more=0，停止")
            break

        cursor = new_cursor
        time.sleep(2.5)

    # 增量追加到 master CSV
    if entries:
        with open(MASTER_CSV, "a" if existing_ids else "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if not existing_ids:
                writer.writerow(["video_id", "title", "cover_url"])
            writer.writerows(entries)
        total = sum(1 for _ in open(MASTER_CSV)) - 1
        logger.info(f"===== 完成: 新增 {len(entries)} 条, 总计 {total} 条 =====")
    else:
        logger.info("===== 无新增 =====")


if __name__ == "__main__":
    fetch_all()
