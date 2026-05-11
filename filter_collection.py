"""
SV2TEXT — 下载前智能过滤模块
基于视频标题 + 封面图，用 Qwen 判断是否与求职相关。
"""

import re
import csv
import json
import time
import base64
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from tqdm import tqdm
from config import (
    QWEN_API_KEY, QWEN_MODEL, QWEN_BASE_URL, ENABLE_FILTER,
    MAX_CONCURRENCY, MAX_RETRIES, RETRY_BASE_DELAY,
    get_csv_file, get_filtered_csv_file, get_filter_checkpoint, setup_logging,
)

logger = setup_logging("filter")

FILTER_SYSTEM_PROMPT = """\
你是一个内容分类助手。你的任务是判断一个短视频是否与求职、简历、面试、\
职场、招聘、工作相关。

只返回 JSON，不要额外文本。"""

FILTER_USER_PROMPT = """\
请根据以下信息判断这个视频是否与求职/简历/面试/职场/招聘/工作/AI技术相关。

标题：{title}

请返回 JSON：
{{
  "relevant": true/false,
  "reason": "简短说明判断理由，10字以内"
}}

判断标准：
- true：标题包含求职、简历、面试、职场、招聘、HR、offer、跳槽、加薪、\
  自我介绍、笔试、群面、校招、社招、实习、转正、年终奖等关键词，\
  或与 AI 技术/大模型/Agent 开发/编程/人工智能相关，\
  或封面图中有相关文字/场景
- false：与上述内容完全无关（美食、娱乐、游戏、旅行、美妆、影视、宠物等）"""


def _load_urls() -> list[tuple[str, str, str, str]]:
    csv_file = get_csv_file()
    if not csv_file.exists():
        return []
    entries = []
    with open(csv_file, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                entries.append((row[0], row[1],
                                row[2] if len(row) >= 3 else f"https://www.douyin.com/video/{row[0]}",
                                row[3] if len(row) >= 4 else ""))
    return entries


def _load_filter_checkpoint() -> dict:
    cp = get_filter_checkpoint()
    if cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_filter_checkpoint(checkpoint: dict):
    cp = get_filter_checkpoint()
    cp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


def _download_cover(cover_url: str) -> str | None:
    if not cover_url:
        return None
    try:
        resp = requests.get(cover_url, timeout=10)
        resp.raise_for_status()
        return base64.b64encode(resp.content).decode("utf-8")
    except Exception:
        return None


def _call_filter_api(title: str, cover_b64: str | None) -> dict:
    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    content = []
    if cover_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{cover_b64}"},
        })
    content.append({"type": "text", "text": FILTER_USER_PROMPT.format(title=title)})

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {"role": "system", "content": FILTER_SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            raw = response.choices[0].message.content or "{}"
            return _parse_filter_response(raw)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
            else:
                return {"relevant": True, "reason": f"API异常: {e}"}
    return {"relevant": True, "reason": "重试耗尽，默认保留"}


def _parse_filter_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"relevant": True, "reason": "解析失败，默认保留"}


def _judge_single(video_id: str, title: str, cover_url: str,
                  checkpoint: dict) -> tuple[str, bool, str]:
    if video_id in checkpoint:
        cached = checkpoint[video_id]
        return video_id, cached.get("relevant", True), cached.get("reason", "缓存")
    cover_b64 = _download_cover(cover_url)
    result = _call_filter_api(title, cover_b64)
    return video_id, result.get("relevant", True), result.get("reason", "未知")


def filter_all(incremental: bool = False):
    logger.info("===== 开始智能过滤 =====")
    if not ENABLE_FILTER:
        logger.info("过滤功能已关闭，跳过")
        return

    entries = _load_urls()
    if not entries:
        logger.warning("CSV 数据文件为空或不存在，请先运行 fetch")
        return

    checkpoint = _load_filter_checkpoint()
    if incremental:
        to_filter = [(vid, t, u, c) for vid, t, u, c in entries if vid not in checkpoint]
        logger.info(f"增量模式: 已有 {len(checkpoint)} 条缓存，新增 {len(to_filter)} 条待过滤")
    else:
        to_filter = entries
        logger.info(f"全量模式: {len(to_filter)} 条待过滤")

    new_results = {}
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        future_map = {
            executor.submit(_judge_single, vid, title, cover_url, checkpoint): vid
            for vid, title, _, cover_url in to_filter
        }
        for future in tqdm(as_completed(future_map), total=len(to_filter),
                           desc="过滤进度", unit="条"):
            vid = future_map[future]
            try:
                vid, is_relevant, reason = future.result()
                new_results[vid] = {"relevant": is_relevant, "reason": reason}
            except Exception as e:
                new_results[vid] = {"relevant": True, "reason": f"异常: {e}"}

    checkpoint.update(new_results)
    _save_filter_checkpoint(checkpoint)

    passed = []
    filtered_out = []
    for vid, title, url, _ in entries:
        result = checkpoint.get(vid, {"relevant": True})
        if result.get("relevant", True):
            passed.append((vid, title, url))
        else:
            filtered_out.append((vid, title, result.get("reason", "")))

    csv_file = get_filtered_csv_file()
    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["video_id", "title", "url"])
        writer.writerows(passed)

    logger.info(f"===== 过滤完成 =====")
    logger.info(f"  总计: {len(entries)} 条 / 保留: {len(passed)} 条 / 过滤: {len(filtered_out)} 条")
    logger.info(f"  结果保存至: {csv_file}")

    if filtered_out:
        logger.info("被过滤的视频:")
        for vid, title, reason in filtered_out[:20]:
            logger.info(f"  ✗ {title[:30]} — {reason}")
        if len(filtered_out) > 20:
            logger.info(f"  ... 还有 {len(filtered_out) - 20} 条")


if __name__ == "__main__":
    filter_all()
