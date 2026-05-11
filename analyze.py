"""
SV2TEXT — AI 分析核心模块
抽帧 → 调用 Qwen 视觉模型 → JSON 解析 → 生成报告。
"""

import os, re, csv, json, time, base64, shutil, subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI
from tqdm import tqdm
from config import (
    QWEN_API_KEY, QWEN_MODEL, QWEN_BASE_URL, QWEN_MODEL_FALLBACKS,
    FRAME_DIR, AUDIO_DIR, SCORE_THRESHOLD,
    MAX_CONCURRENCY, MAX_FRAMES, MAX_RETRIES, RETRY_BASE_DELAY,
    ENABLE_AUDIO, get_video_dir, get_report_dir, get_checkpoint_dir,
    get_csv_file, SESSION_TS, setup_logging,
)

logger = setup_logging("analyze")

_token_stats = {"input": 0, "output": 0, "video_count": 0}

# ─── Prompt（超详细版）───────────────────────────────────────────────
SYSTEM_PROMPT = """\
你是一位顶级的求职顾问和内容分析师。你的任务是对求职相关视频/图文进行\
极度详细的逐帧分析，提取每一条可能有用的信息。你的分析结果将直接成为用户\
的求职参考手册，用户依赖你的分析来替代自己逐条观看。

核心原则：
1. 不遗漏任何企业名称、岗位名称、薪资数字、截止日期、投递渠道
2. 不遗漏任何具体的方法论、技巧、模板、话术
3. 不遗漏任何数据（录取率、薪资范围、竞争比等）
4. 逐帧扫描文字、图表、PPT、弹幕中的所有关键信息
5. 如果是图片/截图，逐张阅读图片中的文字内容

请严格按照指定的 JSON 格式返回分析结果，不要添加任何额外文本。"""

USER_PROMPT_BASE = """\
请对这个求职相关的内容进行极度详尽的分析。你是用户的"AI替身"，\
替用户观看并整理所有关键信息，用户不会再回去看原视频/图文。

请返回以下 JSON 格式（纯 JSON，不要包含 markdown 代码块标记）：
{
  "title": "核心主题，15字以内",
  "category": "简历优化|面试技巧|招聘信息|求职经验|职场建议|行业分析|无关",
  "score": "1-5的整数评分",
  "detailed_summary": "详细内容总结，不少于100字，包含：讲了什么、谁讲的、\
    适用人群、核心观点。不要遗漏任何企业名、岗位名、数字、截止日期。",
  "company_names": ["视频中提到的所有企业/机构名称，每个都要单独列出，不要合并"],
  "job_positions": ["所有被提及的具体岗位名称"],
  "key_techniques": ["视频中传授的所有具体方法、技巧、策略，每条都要详细描述"],
  "key_data": ["所有提到的数字：薪资、人数、比例、日期、金额等"],
  "actionable_tips": ["用户看完可以立刻执行的具体行动，每条描述完整步骤"],
  "key_quotes": ["视频中的关键金句、原话引用，最多5条"],
  "resource_links": ["提到的所有投递链接、官网地址、公众号名称、微信号等"],
  "target_audience": "最适合哪类人群（毕业时间、专业、经验等），具体描述",
  "verdict": "有实用价值 或 低价值 或 无关",
  "filter_reason": "如果verdict不是'有实用价值'，说明具体原因"
}

评分标准：
- 5分：有具体的企业/岗位/薪资/截止日期等硬信息，可直接投递或应用
- 4分：有明确的方法论或渠道，可以立即指导行动
- 3分：通用建议，有参考价值但缺少具体细节
- 2分：内容空泛，主要是鸡汤或引流话术
- 1分：纯营销、无实质内容、与求职完全无关"""
MAX_ANALYSIS_TOKENS = 4096


# ─── 视频预处理 ──────────────────────────────────────────────────────
def probe_duration(video_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr}")
    return float(result.stdout.strip())


def extract_frames(video_path: Path, video_id: str) -> list[Path]:
    """从视频抽帧"""
    duration = probe_duration(video_path)
    fps = "1/3" if duration <= 60 else ("1/5" if duration <= 180 else "1/10")
    frame_subdir = FRAME_DIR / video_id
    frame_subdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vf", f"fps={fps}",
         "-q:v", "2", str(frame_subdir / "%04d.jpg")],
        check=True, capture_output=True,
    )
    frames = sorted(frame_subdir.glob("*.jpg"))
    if len(frames) > MAX_FRAMES:
        step = len(frames) / MAX_FRAMES
        frames = [frames[int(i * step)] for i in range(MAX_FRAMES)]
    return frames


def encode_frame(frame_path: Path) -> str:
    with open(frame_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ─── 音频 ────────────────────────────────────────────────────────────
def extract_audio(video_path: Path, video_id: str) -> Path | None:
    try:
        audio_path = AUDIO_DIR / f"{video_id}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-vn",
             "-acodec", "libmp3lame", "-b:a", "64k", "-ar", "16000", str(audio_path)],
            check=True, capture_output=True, timeout=60,
        )
        return audio_path
    except Exception:
        return None


def _transcribe_audio(audio_path: Path) -> str | None:
    if not ENABLE_AUDIO: return None
    try:
        with open(audio_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        client = get_qwen_client()
        resp = client.chat.completions.create(
            model=os.getenv("AUDIO_MODEL", QWEN_MODEL),
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "请将以下音频转写为文字，只输出转写文本。"},
                {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}},
            ]}],
            temperature=0.0, max_tokens=1024,
        )
        return resp.choices[0].message.content or ""
    except Exception:
        return None


def _cleanup_frames(video_id: str):
    for d in [FRAME_DIR / video_id, AUDIO_DIR / f"{video_id}.mp3"]:
        if d.exists():
            try: shutil.rmtree(d) if d.is_dir() else d.unlink()
            except OSError: pass


# ─── Qwen API ────────────────────────────────────────────────────────
_qwen_client: OpenAI | None = None


def get_qwen_client() -> OpenAI:
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    return _qwen_client


def build_user_content(frame_paths: list[Path], audio_text: str | None) -> list[dict]:
    content: list[dict] = []
    for fp in frame_paths:
        b64 = encode_frame(fp)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    prompt_text = USER_PROMPT_BASE
    if audio_text:
        prompt_text = (
            f"以下是从视频音频中转录的文字，请作为分析内容的补充参考：\n\n"
            f"[音频转录开始]\n{audio_text[:2000]}\n[音频转录结束]\n\n{USER_PROMPT_BASE}"
        )
    content.append({"type": "text", "text": prompt_text})
    return content


def call_qwen_api(frame_paths: list[Path], audio_text: str | None = None) -> str:
    client = get_qwen_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_content(frame_paths, audio_text)},
    ]

    for model in QWEN_MODEL_FALLBACKS:
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = client.chat.completions.create(
                    model=model, messages=messages,
                    temperature=0.0, max_tokens=MAX_ANALYSIS_TOKENS,
                )
                if getattr(resp, 'usage', None):
                    _token_stats["input"] += resp.usage.prompt_tokens or 0
                    _token_stats["output"] += resp.usage.completion_tokens or 0
                    _token_stats["video_count"] += 1
                if model != QWEN_MODEL:
                    logger.info(f"  模型已切换至: {model}")
                return resp.choices[0].message.content or ""
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"  模型 {model} 失败 (attempt {attempt + 1}/{MAX_RETRIES}), {delay}s 后重试")
                    time.sleep(delay)
        logger.warning(f"  模型 {model} 耗尽，切换至下一个模型")
    raise RuntimeError(f"所有模型均失败，最后错误: {last_error}")


# ─── JSON 解析 ───────────────────────────────────────────────────────
def parse_json_response(raw: str) -> dict:
    text = raw.strip()
    cleaned = _strip_markdown_fence(text)
    try: return json.loads(cleaned)
    except json.JSONDecodeError: pass
    for method in [
        lambda: re.search(r'\{[^{}]*\}', cleaned, re.DOTALL),
        lambda: _extract_balanced_json(cleaned),
    ]:
        m = method()
        if m:
            try: return json.loads(m if isinstance(m, str) else m.group())
            except json.JSONDecodeError: pass
    repaired = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try: return json.loads(repaired)
    except json.JSONDecodeError: pass
    raise ValueError(f"JSON 解析失败，原始响应前 500 字符:\n{raw[:500]}")


def _strip_markdown_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"): t = t[:-3]
        return t.strip()
    return t


def _extract_balanced_json(text: str) -> str | None:
    start = text.find("{")
    if start == -1: return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{": depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0: return text[start:i + 1]
    return None


# ─── 断点续传 ────────────────────────────────────────────────────────
def load_checkpoint(video_id: str) -> dict | None:
    path = get_checkpoint_dir() / f"{video_id}.json"
    if path.exists():
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError): pass
    return None


def save_checkpoint(video_id: str, result: dict):
    path = get_checkpoint_dir() / f"{video_id}.json"
    result["analyzed_at"] = datetime.now().isoformat()
    result["model"] = QWEN_MODEL
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── 单条分析 ────────────────────────────────────────────────────────
def analyze_single(video_path: Path, video_id: str, reanalyze: bool = False) -> dict:
    if not reanalyze:
        cached = load_checkpoint(video_id)
        if cached and "error" not in cached:
            return cached

    frame_paths = []
    try:
        # 检测是否为图片序列目录（非视频文件）
        if video_path.is_dir():
            frame_paths = sorted(video_path.glob("*.jpg")) + sorted(video_path.glob("*.png"))
            if not frame_paths:
                raise RuntimeError("图片目录为空")
        else:
            frame_paths = extract_frames(video_path, video_id)

        audio_text = None
        if ENABLE_AUDIO and not video_path.is_dir():
            ap = extract_audio(video_path, video_id)
            if ap: audio_text = _transcribe_audio(ap)

        raw = call_qwen_api(frame_paths, audio_text)
        result = parse_json_response(raw)
        result["video_id"] = video_id
        result["frames_count"] = len(frame_paths)
        if audio_text: result["audio_transcript"] = audio_text[:200]
        save_checkpoint(video_id, result)
        return result

    except Exception as e:
        logger.error(f"分析失败 {video_id}: {e}")
        error_result = {
            "video_id": video_id, "title": "分析失败", "category": "无关",
            "score": 0, "detailed_summary": f"分析失败: {str(e)[:80]}",
            "company_names": [], "job_positions": [], "key_techniques": [],
            "key_data": [], "actionable_tips": [], "key_quotes": [],
            "resource_links": [], "target_audience": "",
            "verdict": "低价值", "filter_reason": f"分析失败: {str(e)[:80]}",
            "error": str(e), "frames_count": len(frame_paths),
        }
        save_checkpoint(video_id, error_result)
        return error_result
    finally:
        if not video_path.is_dir():
            _cleanup_frames(video_id)


# ─── 批量分析 ────────────────────────────────────────────────────────
def _discover_videos() -> list[tuple[Path, str]]:
    video_dir = get_video_dir()
    videos = []
    # MP4/WebM/MKV 视频文件
    for pattern in ("*.mp4", "*.webm", "*.mkv"):
        for f in sorted(video_dir.glob(pattern)):
            vid_id = f.stem.split("_")[0]
            videos.append((f, vid_id))
    # 图片序列目录（图文笔记）
    for d in sorted(video_dir.iterdir()):
        if d.is_dir() and d.name.startswith("note_"):
            vid_id = d.name.replace("note_", "")
            videos.append((d, vid_id))
    return videos


def analyze_all(reanalyze: bool = False) -> int:
    logger.info("===== 开始 AI 分析 =====")
    logger.info(f"模型: {QWEN_MODEL}, 并发: {MAX_CONCURRENCY}, 音频: {'启用' if ENABLE_AUDIO else '关闭'}")

    items = _discover_videos()
    if not items:
        logger.warning(f"{get_video_dir()} 目录为空")
        return 0

    logger.info(f"待分析: {len(items)} 条")
    start_time = time.monotonic()
    _token_stats["input"] = _token_stats["output"] = 0
    _token_stats["video_count"] = 0

    results: dict[str, dict] = {}
    success_count = fail_count = 0
    per_video_times: dict[str, float] = {}

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        future_map = {
            executor.submit(analyze_single, vpath, vid, reanalyze): vid
            for vpath, vid in items
        }
        with tqdm(total=len(items), desc="分析进度", unit="条") as pbar:
            for future in as_completed(future_map):
                vid = future_map[future]
                t_start = time.monotonic()
                try:
                    result = future.result()
                    results[vid] = result
                    elapsed = time.monotonic() - t_start
                    per_video_times[vid] = elapsed
                    if "error" not in result:
                        success_count += 1
                        logger.info(f"✓ {vid} 评分:{result.get('score','N/A')} "
                                    f"分类:{result.get('category','N/A')} ({elapsed:.1f}s)")
                    else:
                        fail_count += 1
                except Exception as e:
                    fail_count += 1
                    results[vid] = {"video_id": vid, "error": str(e)}
                    per_video_times[vid] = time.monotonic() - t_start
                pbar.update(1)

    total_time = time.monotonic() - start_time
    logger.info(f"===== 分析完成: 成功 {success_count}, 失败 {fail_count}, "
                f"总耗时 {total_time:.1f}s =====")
    _generate_report(results, total_time, per_video_times)
    return success_count


# ─── 报告生成 ───────────────────────────────────────────────────────
def _load_metadata() -> dict[str, tuple[str, str, str]]:
    metadata = {}
    csv_file = get_csv_file()
    if csv_file.exists():
        with open(csv_file, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 3:
                    metadata[row[0]] = (row[0], row[1], row[2])
    return metadata


def _meta_title(metadata, vid, fallback="未知标题"):
    _, title, _ = metadata.get(vid, (vid, fallback, ""))
    return title


def _meta_url(metadata, vid):
    _, _, url = metadata.get(vid, (vid, "", ""))
    return url if url else f"https://www.douyin.com/video/{vid}"


def _part_classify(results):
    high_value, by_category, filtered, fail_entries = [], {}, [], []
    for r in results.values():
        if r.get("error"): fail_entries.append(r); continue
        s = int(r.get("score", 0))
        cat = r.get("category", "未分类")
        if s >= SCORE_THRESHOLD:
            by_category.setdefault(cat, []).append(r)
            if s >= 4: high_value.append(r)
        else:
            filtered.append(r)
    return high_value, by_category, filtered, fail_entries


def _build_report_header(total, fail, high, low, total_time):
    return [
        f"# 抖音收藏视频分析报告", "",
        f"> 生成时间: {datetime.now().isoformat()}",
        f"> 模型: {QWEN_MODEL}  |  视频: {total} 条",
        f"> 分析成功: {total - fail}  |  失败: {fail}",
        f"> 高价值(>=4分): {high}  |  已过滤: {low}",
        f"> 总耗时: {total_time:.0f}s", "", "---",
    ]


def _build_cost_section():
    inp, out = _token_stats["input"], _token_stats["output"]
    if inp + out == 0: return []
    cost = inp * 0.2 / 1_000_000 + out * 2.0 / 1_000_000
    return ["", "## 💰 成本统计", "",
            f"- 输入 Token: {inp:,}  /  输出 Token: {out:,}",
            f"- 预估费用: 约 {cost:.2f} 元（{QWEN_MODEL}）", ""]


def _build_timing_section(total_time, per_video_times, metadata):
    if not per_video_times: return []
    avg = total_time / len(per_video_times)
    fastest = min(per_video_times.items(), key=lambda x: x[1])
    slowest = max(per_video_times.items(), key=lambda x: x[1])
    return ["", "## ⏱️ 运行时间", "",
            f"- 总耗时: {total_time:.0f}s  |  平均: {avg:.1f}s/条",
            f"- 最快: {fastest[1]:.1f}s  |  最慢: {slowest[1]:.1f}s", ""]


def _build_summary_section(by_category, filtered):
    lines = ["", "## 📊 汇总统计", "", "| 分类 | 数量 | 平均评分 |", "|------|------|---------|"]
    for cat, entries in sorted(by_category.items()):
        avg = sum(int(r.get("score", 0)) for r in entries) / len(entries)
        lines.append(f"| {cat} | {len(entries)} | {avg:.1f} |")
    if filtered: lines.append(f"| 已过滤 | {len(filtered)} | — |")
    lines.extend(["", "---"])
    return lines


def _build_high_value_section(high_value, metadata):
    if not high_value: return []
    high_value.sort(key=lambda r: int(r.get("score", 0)), reverse=True)
    lines = ["", "## ⭐ 高价值内容（评分 >= 4）", ""]
    for i, r in enumerate(high_value, 1):
        vid = r.get("video_id", "")
        title = _meta_title(metadata, vid)
        summary = r.get("detailed_summary", r.get("summary", ""))
        companies = ", ".join(r.get("company_names", [])) or "—"
        positions = ", ".join(r.get("job_positions", [])) or "—"
        techniques = r.get("key_techniques", [])
        data = r.get("key_data", [])
        tips = r.get("actionable_tips", [])
        quotes = r.get("key_quotes", [])
        links = r.get("resource_links", [])
        audience = r.get("target_audience", "—")

        lines.extend([
            f"### {i}. {title}",
            f"- **评分**: {int(r.get('score', 0)) * '⭐'} ({r.get('score')}/5)",
            f"- **分类**: {r.get('category')}",
            f"- **详细总结**: {summary}",
            f"- **🏢 企业/机构**: {companies}",
            f"- **💼 岗位**: {positions}",
            f"- **🎯 适用人群**: {audience}",
        ])
        if techniques:
            lines.append("- **🔧 关键技巧**:")
            for t in techniques:
                lines.append(f"  - {t}")
        if tips:
            lines.append("- **✅ 可执行行动**:")
            for t in tips:
                lines.append(f"  - {t}")
        if data:
            lines.append("- **📊 关键数据**:")
            for d in data:
                lines.append(f"  - {d}")
        if quotes:
            lines.append("- **💬 关键引用**:")
            for q in quotes:
                lines.append(f"  - {q}")
        if links:
            lines.append("- **🔗 投递渠道**:")
            for l in links:
                lines.append(f"  - {l}")
        lines.extend([
            f"- **来源**: {_meta_url(metadata, vid)}",
            "",
            "---",
            "",
        ])
    return lines


def _build_category_section(by_category, metadata):
    lines = ["## 📋 全部内容（按分类）", ""]
    for cat in sorted(by_category.keys()):
        entries = by_category[cat]
        lines.append(f"### {cat}（{len(entries)}条）")
        lines.extend(["", "| # | 标题 | 评分 | 企业 | 关键内容 |", "|---|------|------|------|------|"])
        for i, r in enumerate(entries, 1):
            vid = r.get("video_id", "")
            companies = ", ".join(r.get("company_names", [])[:2] or []) or "—"
            summary = r.get("detailed_summary", "")[:60]
            lines.append(f"| {i} | {_meta_title(metadata, vid)[:20]} | "
                         f"{int(r.get('score', 0)) * '⭐'} | "
                         f"{companies[:25]} | {summary} |")
        lines.append("")
    return lines


def _build_fail_section(fail_entries, metadata):
    if not fail_entries: return []
    lines = [f"### 分析失败（{len(fail_entries)}条）", "",
             "| # | 标题 | 视频ID | 失败原因 |", "|---|------|--------|---------|"]
    for i, r in enumerate(fail_entries, 1):
        vid = r.get("video_id", "N/A")
        lines.append(f"| {i} | {_meta_title(metadata, vid, vid)[:20]} | "
                     f"{vid} | {r.get('error', 'N/A')[:60]} |")
    lines.append("")
    return lines


def _build_filtered_section(filtered, metadata):
    filtered = [r for r in filtered if not r.get("error")]
    if not filtered: return []
    lines = [f"### 已过滤内容（{len(filtered)}条）", "",
             "> 以下内容因空泛/营销/无关而被过滤", "",
             "| # | 标题 | 评分 | 过滤原因 |", "|---|------|------|---------|"]
    for i, r in enumerate(filtered, 1):
        vid = r.get("video_id", "")
        lines.append(f"| {i} | {_meta_title(metadata, vid)[:30]} | "
                     f"{int(r.get('score', 0)) * '⭐'} | "
                     f"{r.get('filter_reason', '评分过低')[:40]} |")
    lines.append("")
    return lines


def _generate_report(results, total_time=0.0, per_video_times=None):
    metadata = _load_metadata()
    high_value, by_category, filtered, fail_entries = _part_classify(results)
    total = len(results)
    fail_count = len(fail_entries)
    high_count = len([r for r in results.values() if not r.get("error")
                       and int(r.get("score", 0)) >= SCORE_THRESHOLD])

    sections = (
        _build_report_header(total, fail_count, high_count, total - high_count - fail_count, total_time)
        + _build_cost_section()
        + _build_timing_section(total_time, per_video_times or {}, metadata)
        + _build_summary_section(by_category, filtered)
        + _build_high_value_section(high_value, metadata)
        + _build_category_section(by_category, metadata)
        + _build_fail_section(fail_entries, metadata)
        + _build_filtered_section(filtered, metadata)
    )

    report_dir = get_report_dir()
    md_path = report_dir / "analysis_report.md"
    md_path.write_text("\n".join(sections), encoding="utf-8")
    logger.info(f"Markdown 报告: {md_path}")

    json_path = report_dir / "analysis_report.json"
    json_path.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(), "model": QWEN_MODEL,
        "total": total, "success": total - fail_count, "failed": fail_count,
        "high_value": high_count, "total_time_s": total_time,
        "token_stats": dict(_token_stats), "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"JSON 报告: {json_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--reanalyze", action="store_true")
    analyze_all(reanalyze=parser.parse_args().reanalyze)
