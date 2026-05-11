import json
import csv
import pytest


class TestLoadUrls:

    def test_normal_parse_csv(self, tmp_project, monkeypatch):
        path = tmp_project / "fetch_test.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["video_id", "title", "url", "cover_url"])
            w.writerow(["123", "标题1", "http://url1", "http://cover1.jpg"])
            w.writerow(["456", "标题2", "http://url2", "http://cover2.jpg"])

        import filter_collection
        monkeypatch.setattr(filter_collection, "get_csv_file", lambda: path)
        entries = filter_collection._load_urls()
        assert len(entries) == 2
        assert entries[0] == ("123", "标题1", "http://url1", "http://cover1.jpg")
        assert entries[1] == ("456", "标题2", "http://url2", "http://cover2.jpg")

    def test_no_cover_url(self, tmp_project, monkeypatch):
        path = tmp_project / "fetch_test.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["video_id", "title", "url"])
            w.writerow(["123", "标题1", "http://url1"])

        import filter_collection
        monkeypatch.setattr(filter_collection, "get_csv_file", lambda: path)
        entries = filter_collection._load_urls()
        assert len(entries) == 1
        # cover_url defaults to "" when column missing
        assert entries[0][3] == ""

    def test_empty_file(self, tmp_project, monkeypatch):
        import filter_collection
        monkeypatch.setattr(filter_collection, "get_csv_file", lambda: tmp_project / "nonexistent.csv")
        entries = filter_collection._load_urls()
        assert entries == []


class TestParseFilterResponse:

    def test_valid_json(self):
        from filter_collection import _parse_filter_response
        result = _parse_filter_response('{"relevant": true, "reason": "求职相关"}')
        assert result["relevant"] is True
        assert result["reason"] == "求职相关"

    def test_markdown_wrapped(self):
        from filter_collection import _parse_filter_response
        raw = '```json\n{"relevant": false, "reason": "美食视频"}\n```'
        result = _parse_filter_response(raw)
        assert result["relevant"] is False
        assert result["reason"] == "美食视频"

    def test_parse_failure_defaults_true(self):
        from filter_collection import _parse_filter_response
        result = _parse_filter_response("not json at all")
        assert result["relevant"] is True
        assert "默认保留" in result["reason"]

    def test_empty_response(self):
        from filter_collection import _parse_filter_response
        result = _parse_filter_response("")
        assert result["relevant"] is True


class TestCheckpoint:

    def test_load_nonexistent(self, tmp_project, monkeypatch):
        import filter_collection
        monkeypatch.setattr(
            filter_collection, "get_filter_checkpoint",
            lambda: tmp_project / "nonexistent.json"
        )
        result = filter_collection._load_filter_checkpoint()
        assert result == {}

    def test_save_and_load(self, tmp_project, monkeypatch):
        import filter_collection
        checkpoint_path = tmp_project / "filter_checkpoint.json"
        monkeypatch.setattr(filter_collection, "get_filter_checkpoint", lambda: checkpoint_path)

        data = {"123": {"relevant": True, "reason": "测试"}}
        filter_collection._save_filter_checkpoint(data)
        loaded = filter_collection._load_filter_checkpoint()
        assert loaded["123"]["relevant"] is True

    def test_load_corrupted(self, tmp_project, monkeypatch):
        import filter_collection
        checkpoint_path = tmp_project / "filter_checkpoint.json"
        checkpoint_path.write_text("not json!!!")
        monkeypatch.setattr(filter_collection, "get_filter_checkpoint", lambda: checkpoint_path)
        result = filter_collection._load_filter_checkpoint()
        assert result == {}


class TestCallFilterApi:

    def test_relevant_response(self, tmp_project, monkeypatch):
        import filter_collection

        class MockMessage:
            content = '{"relevant": true, "reason": "求职面试"}'

        class MockChoice:
            message = MockMessage()

        class MockResponse:
            choices = [MockChoice()]

        class MockClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        return MockResponse()

        monkeypatch.setattr("filter_collection.OpenAI", lambda *a, **kw: MockClient())
        result = filter_collection._call_filter_api("面试技巧分享", None)
        assert result["relevant"] is True

    def test_api_error_defaults_true(self, tmp_project, monkeypatch):
        import filter_collection
        import time

        class MockClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        raise Exception("Network error")

        monkeypatch.setattr("filter_collection.OpenAI", lambda *a, **kw: MockClient())
        monkeypatch.setattr("filter_collection.MAX_RETRIES", 1)
        monkeypatch.setattr("filter_collection.RETRY_BASE_DELAY", 0.01)
        monkeypatch.setattr(time, "sleep", lambda x: None)

        result = filter_collection._call_filter_api("test", None)
        assert result["relevant"] is True


class TestJudgeSingle:

    def test_cached_checkpoint(self, monkeypatch):
        import filter_collection
        checkpoint = {"123": {"relevant": False, "reason": "已缓存为无关"}}

        vid, relevant, reason = filter_collection._judge_single(
            "123", "test", "", checkpoint
        )
        assert relevant is False
        assert "缓存" in reason

    def test_not_cached_calls_api(self, monkeypatch):
        import filter_collection

        def mock_call(title, cover):
            return {"relevant": True, "reason": "求职相关"}

        monkeypatch.setattr(filter_collection, "_download_cover", lambda url: None)
        monkeypatch.setattr(filter_collection, "_call_filter_api", mock_call)

        vid, relevant, reason = filter_collection._judge_single(
            "999", "简历优化", "", {}
        )
        assert relevant is True
