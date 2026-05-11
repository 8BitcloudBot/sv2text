import pytest
import subprocess
from pathlib import Path


class TestReadUrls:

    def test_normal_parse(self, sample_csv_file, monkeypatch):
        import download
        monkeypatch.setattr(download, "get_filtered_csv_file", lambda: sample_csv_file.parent / "nonexistent.csv")
        monkeypatch.setattr(download, "get_csv_file", lambda: sample_csv_file)
        entries = download._read_urls()
        assert len(entries) == 2
        assert entries[0] == ("123", "测试标题一", "https://www.douyin.com/video/123")

    def test_file_not_found(self, tmp_project, monkeypatch):
        import download
        monkeypatch.setattr(download, "get_filtered_csv_file", lambda: tmp_project / "nonexistent_f.csv")
        monkeypatch.setattr(download, "get_csv_file", lambda: tmp_project / "nonexistent.csv")
        with pytest.raises(FileNotFoundError):
            download._read_urls()

    def test_prefers_filtered_csv(self, tmp_project, monkeypatch):
        import csv
        raw = tmp_project / "raw.csv"
        filtered = tmp_project / "filtered.csv"
        with open(raw, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["video_id", "title", "url"])
            w.writerow(["111", "原始", "http://url1"])
        with open(filtered, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["video_id", "title", "url"])
            w.writerow(["222", "过滤后", "http://url2"])

        import download
        monkeypatch.setattr(download, "get_filtered_csv_file", lambda: filtered)
        monkeypatch.setattr(download, "get_csv_file", lambda: raw)
        entries = download._read_urls()
        assert len(entries) == 1
        assert entries[0][0] == "222"


class TestVerifyVideo:

    def test_valid_video(self, tmp_project, monkeypatch):
        import download

        class MockResult:
            returncode = 0
            stdout = "63.5\n"

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: MockResult())
        assert download.verify_video(tmp_project / "test.mp4") is True

    def test_short_video(self, tmp_project, monkeypatch):
        import download

        class MockResult:
            returncode = 0
            stdout = "0.5\n"

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: MockResult())
        assert download.verify_video(tmp_project / "test.mp4") is False

    def test_ffprobe_failure(self, tmp_project, monkeypatch):
        import download

        class MockResult:
            returncode = 1
            stdout = ""

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: MockResult())
        assert download.verify_video(tmp_project / "test.mp4") is False

    def test_ffprobe_timeout(self, tmp_project, monkeypatch):
        import download

        def mock_run(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)

        monkeypatch.setattr("subprocess.run", mock_run)
        big_file = tmp_project / "big.mp4"
        big_file.write_bytes(b"\x00" * 20000)
        assert download.verify_video(big_file) is True

        small_file = tmp_project / "small.mp4"
        small_file.write_bytes(b"\x00" * 100)
        assert download.verify_video(small_file) is False


class TestDownloadVideo:

    def test_non_douyin_url_skipped(self, tmp_project, monkeypatch):
        import download
        monkeypatch.setattr(download, "get_video_dir", lambda: tmp_project / "videos")
        monkeypatch.setattr(download, "logger", type("MockLogger", (), {"info": lambda *a: None, "debug": lambda *a: None, "warning": lambda *a: None})())
        result = download.download_video("999", "https://www.bilibili.com/video/test", "非抖音视频")
        assert result is False

    def test_video_cdn_downloaded(self, tmp_project, monkeypatch):
        import download

        info = {"type": "video", "cdn_url": "https://cdn.douyin.com/video.mp4", "image_urls": [], "error": None}

        def mock_get_info(url):
            return info

        def mock_download_from_url(cdn_url, out_path):
            out_path.write_bytes(b"\x00" * 20480)
            monkeypatch.setattr(download, "verify_video", lambda p: True)
            return True

        monkeypatch.setattr(download, "get_download_info", mock_get_info)
        monkeypatch.setattr(download, "_download_from_url", mock_download_from_url)
        monkeypatch.setattr(download, "get_video_dir", lambda: tmp_project / "videos")
        monkeypatch.setattr(download, "logger", type("MockLogger", (), {"info": lambda *a: None, "debug": lambda *a: None, "warning": lambda *a: None})())

        result = download.download_video("888", "https://www.douyin.com/video/888", "测试视频")
        assert result is True

    def test_image_note_downloaded(self, tmp_project, monkeypatch):
        import download

        info = {"type": "image_note", "cdn_url": None, "image_urls": ["https://cdn.douyin.com/img1.jpg"], "error": None}

        def mock_get_info(url):
            return info

        monkeypatch.setattr(download, "get_download_info", mock_get_info)
        monkeypatch.setattr(download, "get_video_dir", lambda: tmp_project / "videos")
        monkeypatch.setattr(download, "logger", type("MockLogger", (), {"info": lambda *a: None, "debug": lambda *a: None, "warning": lambda *a: None})())

        class MockResponse:
            def __init__(self, content):
                self.content = content
            def raise_for_status(self): pass
            headers = {"content-type": "image/jpeg"}

        monkeypatch.setattr("requests.get", lambda url, **kw: MockResponse(b"\xff\xd8" + b"\x00" * 100))

        result = download.download_video("777", "https://www.douyin.com/note/777", "图文笔记")
        assert result is True

    def test_api_failure_falls_back_to_ytdlp(self, tmp_project, monkeypatch):
        import download

        info = {"type": "error", "cdn_url": None, "image_urls": [], "error": "API 请求失败"}

        def mock_get_info(url):
            return info

        def mock_ytdlp(video_id, url, out_path):
            out_path.write_bytes(b"\x00" * 20480)
            return True

        monkeypatch.setattr(download, "get_download_info", mock_get_info)
        monkeypatch.setattr(download, "_download_via_ytdlp", mock_ytdlp)
        monkeypatch.setattr(download, "get_video_dir", lambda: tmp_project / "videos")
        monkeypatch.setattr(download, "logger", type("MockLogger", (), {"info": lambda *a: None, "debug": lambda *a: None, "warning": lambda *a: None})())

        result = download.download_video("666", "https://www.douyin.com/video/666", "失败视频")
        assert result is True
