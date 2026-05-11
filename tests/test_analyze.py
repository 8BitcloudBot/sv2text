import json
import pytest
from pathlib import Path


# ─── 纯函数测试 ──────────────────────────────────────────────────────

class TestStripMarkdownFence:

    def test_with_fence(self):
        from analyze import _strip_markdown_fence
        input_text = '```json\n{"score": 5}\n```'
        assert _strip_markdown_fence(input_text) == '{"score": 5}'

    def test_without_fence(self):
        from analyze import _strip_markdown_fence
        assert _strip_markdown_fence('{"score": 5}') == '{"score": 5}'

    def test_fence_without_lang(self):
        from analyze import _strip_markdown_fence
        input_text = '```\n{"score": 5}\n```'
        assert _strip_markdown_fence(input_text) == '{"score": 5}'

    def test_empty_string(self):
        from analyze import _strip_markdown_fence
        assert _strip_markdown_fence('') == ''


class TestExtractBalancedJson:

    def test_simple_object(self):
        from analyze import _extract_balanced_json
        result = _extract_balanced_json('prefix {"a": 1} suffix')
        assert result == '{"a": 1}'

    def test_nested_object(self):
        from analyze import _extract_balanced_json
        result = _extract_balanced_json('{"a": {"b": 1}}')
        assert result == '{"a": {"b": 1}}'

    def test_no_brace_returns_none(self):
        from analyze import _extract_balanced_json
        assert _extract_balanced_json("no json here") is None

    def test_unclosed_brace_returns_none(self):
        from analyze import _extract_balanced_json
        assert _extract_balanced_json('{"a": 1') is None

    def test_array_with_nested_object(self):
        from analyze import _extract_balanced_json
        result = _extract_balanced_json('text {"arr": [1,2,3]} end')
        assert result == '{"arr": [1,2,3]}'


class TestParseJsonResponse:

    def test_standard_json(self):
        from analyze import parse_json_response
        result = parse_json_response('{"score": 5, "title": "test"}')
        assert result["score"] == 5

    def test_markdown_wrapped(self):
        from analyze import parse_json_response
        raw = '```json\n{"score": 5}\n```'
        result = parse_json_response(raw)
        assert result["score"] == 5

    def test_json_with_prefix_text(self):
        from analyze import parse_json_response
        raw = '分析结果如下：\n{"score": 5, "title": "test"}\n以上是分析结果'
        result = parse_json_response(raw)
        assert result["score"] == 5

    def test_trailing_comma_fixed(self):
        from analyze import parse_json_response
        raw = '{"score": 5, "title": "test",}'
        result = parse_json_response(raw)
        assert result["score"] == 5

    def test_nested_json(self):
        from analyze import parse_json_response
        raw = '```json\n{"title":"test","tips":["a","b"],"score":4}\n```'
        result = parse_json_response(raw)
        assert result["tips"] == ["a", "b"]

    def test_invalid_json_raises(self):
        from analyze import parse_json_response
        with pytest.raises(ValueError, match="JSON 解析失败"):
            parse_json_response("this is not json at all")

    def test_empty_string_raises(self):
        from analyze import parse_json_response
        with pytest.raises(ValueError):
            parse_json_response("")


# ─── 外部依赖测试 ─────────────────────────────────────────────────────

class TestProbeDuration:

    def test_normal_duration(self, tmp_project, monkeypatch):
        from analyze import probe_duration

        class MockResult:
            returncode = 0
            stdout = "125.3\n"
            stderr = ""

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: MockResult())
        duration = probe_duration(tmp_project / "test.mp4")
        assert duration == 125.3

    def test_ffprobe_failure_raises(self, tmp_project, monkeypatch):
        from analyze import probe_duration

        class MockResult:
            returncode = 1
            stdout = ""
            stderr = "No such file"

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: MockResult())
        with pytest.raises(RuntimeError, match="ffprobe 失败"):
            probe_duration(tmp_project / "nonexistent.mp4")


class TestEncodeFrame:

    def test_encode_returns_base64(self, tmp_project):
        import base64
        from analyze import encode_frame

        frame = tmp_project / "test_frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        result = encode_frame(frame)
        decoded = base64.b64decode(result)
        assert decoded[:4] == b"\xff\xd8\xff\xe0"


class TestBuildMessages:

    def test_message_structure(self, tmp_project, monkeypatch):
        from analyze import build_user_content
        import base64

        frames = []
        for i in range(3):
            fp = tmp_project / f"frame_{i:04d}.jpg"
            fp.write_bytes(b"\xff\xd8" + b"\x00" * 50)
            frames.append(fp)

        monkeypatch.setattr(
            "analyze.encode_frame",
            lambda fp: base64.b64encode(fp.read_bytes()).decode()
        )

        content = build_user_content(frames, None)
        assert isinstance(content, list)
        image_count = sum(1 for c in content if c["type"] == "image_url")
        text_count = sum(1 for c in content if c["type"] == "text")
        assert image_count == 3
        assert text_count == 1


class TestCallQwenApi:

    def test_success_returns_text(self, tmp_project, monkeypatch, mock_qwen_json):
        from analyze import call_qwen_api

        class MockMessage:
            content = mock_qwen_json

        class MockChoice:
            message = MockMessage()

        class MockResponse:
            choices = [MockChoice()]
            usage = None

        class MockClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        return MockResponse()

        monkeypatch.setattr("analyze.get_qwen_client", lambda: MockClient())
        monkeypatch.setattr("analyze.build_user_content", lambda fp, audio: [])
        result = call_qwen_api([tmp_project / "fake.jpg"])
        assert "STAR" in result

    def test_retry_on_failure(self, tmp_project, monkeypatch):
        from analyze import call_qwen_api

        call_count = {"n": 0}

        class MockClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        call_count["n"] += 1
                        if call_count["n"] < 3:
                            raise Exception("API Error")
                        class Msg:
                            content = '{"score": 5}'
                        class Choice:
                            message = Msg()
                        class Resp:
                            choices = [Choice()]
                            usage = None
                        return Resp()

        monkeypatch.setattr("analyze.get_qwen_client", lambda: MockClient())
        monkeypatch.setattr("analyze.build_user_content", lambda fp, audio: [])
        monkeypatch.setattr("time.sleep", lambda x: None)
        monkeypatch.setattr("analyze.MAX_RETRIES", 3)
        monkeypatch.setattr("analyze.RETRY_BASE_DELAY", 0.01)

        result = call_qwen_api([tmp_project / "fake.jpg"])
        assert call_count["n"] == 3
        assert "5" in result

    def test_all_retries_fail_raises(self, tmp_project, monkeypatch):
        from analyze import call_qwen_api

        class MockClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        raise Exception("Persistent Error")

        monkeypatch.setattr("analyze.get_qwen_client", lambda: MockClient())
        monkeypatch.setattr("analyze.build_user_content", lambda fp, audio: [])
        monkeypatch.setattr("time.sleep", lambda x: None)
        monkeypatch.setattr("analyze.MAX_RETRIES", 2)
        monkeypatch.setattr("analyze.RETRY_BASE_DELAY", 0.01)

        with pytest.raises(Exception, match="Persistent Error"):
            call_qwen_api([tmp_project / "fake.jpg"])


class TestCheckpoint:

    def test_load_existing_checkpoint(self, tmp_project, monkeypatch, sample_checkpoint):
        from analyze import load_checkpoint
        path, expected = sample_checkpoint
        monkeypatch.setattr("analyze.get_checkpoint_dir", lambda: tmp_project / "reports" / "individual")
        result = load_checkpoint("123")
        assert result is not None
        assert result["score"] == 5
        assert result["category"] == "简历优化"

    def test_load_nonexistent_returns_none(self, tmp_project, monkeypatch):
        from analyze import load_checkpoint
        monkeypatch.setattr("analyze.get_checkpoint_dir", lambda: tmp_project / "reports" / "individual")
        result = load_checkpoint("nonexistent")
        assert result is None

    def test_save_checkpoint_contains_metadata(self, tmp_project, monkeypatch):
        check_dir = tmp_project / "reports" / "individual"
        check_dir.mkdir(parents=True, exist_ok=True)
        from analyze import save_checkpoint
        monkeypatch.setattr("analyze.get_checkpoint_dir", lambda: check_dir)

        save_checkpoint("999", {"title": "test"})
        saved = json.loads((check_dir / "999.json").read_text())
        assert "analyzed_at" in saved
        assert "model" in saved
        assert saved["title"] == "test"


class TestGenerateReport:

    def test_report_file_created(self, tmp_project, monkeypatch, sample_csv_file):
        from analyze import _generate_report
        monkeypatch.setattr("analyze.get_report_dir", lambda: tmp_project / "reports")
        monkeypatch.setattr("analyze.get_csv_file", lambda: sample_csv_file)

        results = {
            "111": {"video_id": "111", "title": "高价值", "category": "简历优化", "score": 5,
                    "detailed_summary": "摘要1", "actionable_tips": ["建议1"], "key_quotes": ["金句1"],
                    "company_names": [], "job_positions": [], "key_techniques": [],
                    "key_data": [], "resource_links": [], "target_audience": "应届生",
                    "verdict": "有实用价值"},
            "222": {"video_id": "222", "title": "低价值", "category": "面试技巧", "score": 2,
                    "detailed_summary": "摘要2", "actionable_tips": [], "key_quotes": [],
                    "company_names": [], "job_positions": [], "key_techniques": [],
                    "key_data": [], "resource_links": [], "target_audience": "",
                    "verdict": "低价值", "filter_reason": "内容空泛"},
            "333": {"video_id": "333", "error": "API 超时"},
        }

        _generate_report(results)

        report_path = tmp_project / "reports" / "analysis_report.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "抖音收藏视频分析报告" in content
        assert "高价值" in content
        assert "分析失败" in content

    def test_high_value_sorted_by_score(self, tmp_project, monkeypatch):
        from analyze import _generate_report
        import csv

        # Create CSV with matching video IDs
        csv_path = tmp_project / "fetch_test.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["video_id", "title", "url"])
            w.writerow(["a", "4分视频", "http://url_a"])
            w.writerow(["b", "5分视频", "http://url_b"])

        monkeypatch.setattr("analyze.get_report_dir", lambda: tmp_project / "reports")
        monkeypatch.setattr("analyze.get_csv_file", lambda: csv_path)

        results = {
            "a": {"video_id": "a", "title": "4分视频", "category": "简历优化", "score": 4,
                  "detailed_summary": "", "actionable_tips": [], "key_quotes": [],
                  "company_names": [], "job_positions": [], "key_techniques": [],
                  "key_data": [], "resource_links": [], "target_audience": "",
                  "verdict": "有实用价值"},
            "b": {"video_id": "b", "title": "5分视频", "category": "简历优化", "score": 5,
                  "detailed_summary": "", "actionable_tips": [], "key_quotes": [],
                  "company_names": [], "job_positions": [], "key_techniques": [],
                  "key_data": [], "resource_links": [], "target_audience": "",
                  "verdict": "有实用价值"},
        }
        _generate_report(results)

        content = (tmp_project / "reports" / "analysis_report.md").read_text()
        pos_5 = content.index("5分视频")
        pos_4 = content.index("4分视频")
        assert pos_5 < pos_4


class TestDiscoverVideos:

    def test_finds_mp4_files(self, tmp_project, monkeypatch):
        vdir = tmp_project / "videos"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "789.mp4").write_bytes(b"\x00" * 1024)
        from analyze import _discover_videos
        monkeypatch.setattr("analyze.get_video_dir", lambda: vdir)
        videos = _discover_videos()
        assert len(videos) == 1
        assert videos[0][1] == "789"

    def test_empty_dir_returns_empty(self, tmp_project, monkeypatch):
        from analyze import _discover_videos
        monkeypatch.setattr("analyze.get_video_dir", lambda: tmp_project / "videos")
        videos = _discover_videos()
        assert videos == []

    def test_finds_multiple_formats(self, tmp_project, monkeypatch):
        vdir = tmp_project / "videos"
        vdir.mkdir(parents=True, exist_ok=True)
        for ext in ["mp4", "webm", "mkv"]:
            (vdir / f"test.{ext}").write_bytes(b"\x00")
        from analyze import _discover_videos
        monkeypatch.setattr("analyze.get_video_dir", lambda: vdir)
        videos = _discover_videos()
        assert len(videos) == 3
