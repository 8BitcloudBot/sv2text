import json
import pytest
import requests
from pathlib import Path


class TestFetchPage:

    def test_normal_response(self, monkeypatch):
        import fetch_collection

        class MockAntiSpam:
            def get_cookie_string(self, base): return base
            def get_fingerprint_params(self): return {}

        class MockABogus:
            def get_value(self, params, method): return "fake_bogus"

        monkeypatch.setattr(fetch_collection, "DouyinAntiSpam", lambda ua: MockAntiSpam())
        monkeypatch.setattr(fetch_collection, "ABogus", lambda ua, p: MockABogus())

        mock_data = {
            "status_code": 0,
            "has_more": 1,
            "cursor": 100,
            "aweme_list": [
                {"aweme_id": "111", "desc": "视频1",
                 "video": {"cover": {"url_list": ["http://cover1.jpg"]}}},
                {"aweme_id": "222", "desc": "视频2",
                 "video": {"cover": {"url_list": ["http://cover2.jpg"]}}},
            ],
        }

        class MockResponse:
            status_code = 200
            def json(self): return mock_data
            def raise_for_status(self): pass

        monkeypatch.setattr("requests.post", lambda *a, **kw: MockResponse())
        result = fetch_collection.fetch_page(cursor=0)
        assert len(result["aweme_list"]) == 2
        assert result["aweme_list"][0]["aweme_id"] == "111"

    def test_error_status_not_raised(self, monkeypatch):
        import fetch_collection

        class MockAntiSpam:
            def get_cookie_string(self, base): return base
            def get_fingerprint_params(self): return {}
        class MockABogus:
            def get_value(self, params, method): return "fake_bogus"

        monkeypatch.setattr(fetch_collection, "DouyinAntiSpam", lambda ua: MockAntiSpam())
        monkeypatch.setattr(fetch_collection, "ABogus", lambda ua, p: MockABogus())

        class MockResponse:
            status_code = 200
            def json(self): return {"status_code": 2, "status_msg": "参数错误"}
            def raise_for_status(self): pass

        monkeypatch.setattr("requests.post", lambda *a, **kw: MockResponse())
        result = fetch_collection.fetch_page()
        assert result["status_code"] == 2

    def test_network_timeout(self, monkeypatch):
        import fetch_collection

        class MockAntiSpam:
            def get_cookie_string(self, base): return base
            def get_fingerprint_params(self): return {}
        class MockABogus:
            def get_value(self, params, method): return "fake_bogus"

        monkeypatch.setattr(fetch_collection, "DouyinAntiSpam", lambda ua: MockAntiSpam())
        monkeypatch.setattr(fetch_collection, "ABogus", lambda ua, p: MockABogus())

        def mock_post(*a, **kw):
            raise requests.Timeout("连接超时")

        monkeypatch.setattr("fetch_collection.requests.post", mock_post)
        with pytest.raises(requests.Timeout):
            fetch_collection.fetch_page()


class TestLoadExistingIds:

    def test_load_from_file(self, sample_master_csv, monkeypatch):
        import fetch_collection
        monkeypatch.setattr(fetch_collection, "MASTER_CSV", sample_master_csv)
        ids = fetch_collection._load_existing_ids()
        assert "111" in ids
        assert "222" in ids
        assert len(ids) == 2

    def test_no_file_returns_empty(self, tmp_project, monkeypatch):
        import fetch_collection
        monkeypatch.setattr(fetch_collection, "MASTER_CSV", tmp_project / "nonexistent.csv")
        ids = fetch_collection._load_existing_ids()
        assert ids == set()


class TestFetchAll:

    def test_fetch_all_incremental_skip_existing(self, tmp_project, monkeypatch):
        import csv
        import fetch_collection

        # Create master CSV with one existing entry
        master = tmp_project / "master.csv"
        with open(master, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["video_id", "title"])
            w.writerow(["existing_id", "已有视频"])

        # Mock API to return one new + one duplicate
        class MockAntiSpam:
            def get_cookie_string(self, base): return base
            def get_fingerprint_params(self): return {}

        class MockABogus:
            def get_value(self, params, method): return "fake_bogus"

        monkeypatch.setattr(fetch_collection, "DouyinAntiSpam", lambda ua: MockAntiSpam())
        monkeypatch.setattr(fetch_collection, "ABogus", lambda ua, p: MockABogus())
        monkeypatch.setattr(fetch_collection, "MASTER_CSV", master)
        monkeypatch.setattr(fetch_collection, "logger", type("MockLogger", (), {"info": lambda *a, **kw: None, "error": lambda *a, **kw: None})())
        monkeypatch.setattr("time.sleep", lambda x: None)

        mock_data = {
            "status_code": 0,
            "has_more": 0,
            "cursor": 0,
            "aweme_list": [
                {"aweme_id": "existing_id", "desc": "已有视频"},
                {"aweme_id": "new_id", "desc": "新视频"},
            ],
        }

        class MockResponse:
            status_code = 200
            def json(self): return mock_data
            def raise_for_status(self): pass

        monkeypatch.setattr("requests.post", lambda *a, **kw: MockResponse())

        fetch_collection.fetch_all(incremental=True)

        # Read master CSV to verify only new entry was added
        entries = []
        with open(master, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if row:
                    entries.append(row)
        assert len(entries) == 2  # existing + new
        assert entries[0][0] == "existing_id"
        assert entries[1][0] == "new_id"
