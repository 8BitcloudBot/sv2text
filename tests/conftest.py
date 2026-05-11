import csv
import json
import pytest
from pathlib import Path


@pytest.fixture
def tmp_project(tmp_path):
    for d in ["videos", "frames", "reports/individual", "logs", "audio"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def sample_csv_file(tmp_project):
    """CSV 格式 fixtures (video_id,title,url,cover_url)，兼容当前 _read_urls / _load_urls"""
    path = tmp_project / "fetch_test.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["video_id", "title", "url", "cover_url"])
        writer.writerow(["123", "测试标题一", "https://www.douyin.com/video/123", "https://cover1.jpg"])
        writer.writerow(["456", "测试标题二", "https://www.douyin.com/video/456", "https://cover2.jpg"])
    return path


@pytest.fixture
def sample_master_csv(tmp_project):
    """master_videos.csv 格式 (video_id,title,cover_url)，3列"""
    path = tmp_project / "master_videos.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["video_id", "title", "cover_url"])
        writer.writerow(["111", "面试技巧分享", "https://cover1.jpg"])
        writer.writerow(["222", "美食探店视频", "https://cover2.jpg"])
    return path


@pytest.fixture
def sample_video(tmp_project):
    video = tmp_project / "videos" / "789_测试视频.mp4"
    video.write_bytes(b"\x00" * 1024)
    return video


@pytest.fixture
def sample_checkpoint(tmp_project):
    result = {
        "video_id": "123",
        "title": "STAR法则",
        "category": "简历优化",
        "score": 5,
        "detailed_summary": "介绍了STAR法则在简历中的应用",
        "actionable_tips": ["用STAR重写项目经历"],
        "key_quotes": ["简历是营销文案"],
        "company_names": [],
        "job_positions": [],
        "key_techniques": [],
        "key_data": [],
        "resource_links": [],
        "target_audience": "应届生",
        "verdict": "有实用价值",
        "filter_reason": None,
        "analyzed_at": "2026-05-10T10:00:00",
        "model": "qwen3.5-flash",
        "frames_count": 10,
    }
    path = tmp_project / "reports" / "individual" / "123.json"
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return path, result


@pytest.fixture
def mock_qwen_json():
    return json.dumps({
        "title": "STAR法则写简历",
        "category": "简历优化",
        "score": 5,
        "detailed_summary": "介绍了STAR法则在简历项目描述中的应用",
        "actionable_tips": [
            "用情境-任务-行动-结果框架重写每条项目经历",
            "量化结果，避免负责XX这类职责描述",
        ],
        "company_names": [],
        "job_positions": [],
        "key_techniques": [],
        "key_data": [],
        "resource_links": [],
        "target_audience": "应届生",
        "key_quotes": ["简历不是工作日志，是你的营销文案"],
        "verdict": "有实用价值",
        "filter_reason": None,
    }, ensure_ascii=False)
