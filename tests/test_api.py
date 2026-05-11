import json
import pytest
from src.douyin.api import (
    extract_aweme_id, extract_cdn_url, extract_note_images,
    is_image_note, get_download_info,
)


class TestExtractAwemeId:

    def test_standard_video_url(self):
        assert extract_aweme_id("https://www.douyin.com/video/123456789") == "123456789"

    def test_video_url_with_query(self):
        assert extract_aweme_id("https://www.douyin.com/video/123456789?previous_page=1") == "123456789"

    def test_note_url(self):
        assert extract_aweme_id("https://www.douyin.com/note/987654321") == "987654321"

    def test_short_url(self):
        # v.douyin.com short links don't have /video/ pattern
        assert extract_aweme_id("https://v.douyin.com/abcd/") is None

    def test_non_douyin_url(self):
        assert extract_aweme_id("https://www.bilibili.com/video/BV123") is None

    def test_empty_string(self):
        assert extract_aweme_id("") is None


class TestExtractCdnUrl:

    def test_highest_quality_selected(self):
        detail = {
            "aweme_detail": {
                "video": {
                    "bit_rate": [
                        {
                            "play_addr": {
                                "url_list": ["https://cdn/low.mp4"],
                                "height": 360, "width": 640, "data_size": 1000,
                            },
                            "FPS": 30, "bit_rate": 500000,
                        },
                        {
                            "play_addr": {
                                "url_list": ["https://cdn/high.mp4"],
                                "height": 1080, "width": 1920, "data_size": 5000,
                            },
                            "FPS": 60, "bit_rate": 2000000,
                        },
                        {
                            "play_addr": {
                                "url_list": ["https://cdn/mid.mp4"],
                                "height": 720, "width": 1280, "data_size": 3000,
                            },
                            "FPS": 30, "bit_rate": 1000000,
                        },
                    ]
                }
            }
        }
        url = extract_cdn_url(detail)
        assert url == "https://cdn/high.mp4"

    def test_empty_bit_rate(self):
        detail = {"aweme_detail": {"video": {"bit_rate": []}}}
        assert extract_cdn_url(detail) is None

    def test_no_video_field(self):
        detail = {"aweme_detail": {}}
        assert extract_cdn_url(detail) is None

    def test_no_aweme_detail(self):
        detail = {"status_code": 2}
        assert extract_cdn_url(detail) is None

    def test_empty_url_list(self):
        detail = {
            "aweme_detail": {
                "video": {
                    "bit_rate": [{
                        "play_addr": {"url_list": []},
                        "FPS": 30, "bit_rate": 1000,
                    }]
                }
            }
        }
        assert extract_cdn_url(detail) is None

    def test_single_bit_rate(self):
        detail = {
            "aweme_detail": {
                "video": {
                    "bit_rate": [{
                        "play_addr": {
                            "url_list": ["https://cdn/only.mp4"],
                            "height": 720, "width": 1280, "data_size": 2000,
                        },
                        "FPS": 30, "bit_rate": 1000000,
                    }]
                }
            }
        }
        url = extract_cdn_url(detail)
        assert url == "https://cdn/only.mp4"


class TestExtractNoteImages:

    def test_extract_images(self):
        detail = {
            "aweme_detail": {
                "images": [
                    {"url_list": ["https://img1.jpg", "https://img1b.jpg"]},
                    {"url_list": ["https://img2.jpg"]},
                ]
            }
        }
        urls = extract_note_images(detail)
        assert urls == ["https://img1.jpg", "https://img2.jpg"]

    def test_no_images(self):
        detail = {"aweme_detail": {"video": {"bit_rate": []}}}
        assert extract_note_images(detail) == []

    def test_empty_images_list(self):
        detail = {"aweme_detail": {"images": []}}
        assert extract_note_images(detail) == []

    def test_empty_url_list(self):
        detail = {"aweme_detail": {"images": [{"url_list": []}]}}
        assert extract_note_images(detail) == []


class TestIsImageNote:

    def test_video_content(self):
        detail = {
            "aweme_detail": {
                "video": {"bit_rate": [{"play_addr": {"url_list": ["url"]}}]}
            }
        }
        assert is_image_note(detail) is False

    def test_image_note_content(self):
        detail = {
            "aweme_detail": {
                "images": [{"url_list": ["url"]}]
            }
        }
        assert is_image_note(detail) is True

    def test_empty_content(self):
        detail = {"aweme_detail": {}}
        assert is_image_note(detail) is False


class TestGetDownloadInfo:

    def test_video_type(self, monkeypatch):
        from src.douyin import api

        def mock_get_detail(aweme_id):
            return {
                "status_code": 0,
                "aweme_detail": {
                    "video": {
                        "bit_rate": [{
                            "play_addr": {
                                "url_list": ["https://cdn/video.mp4"],
                                "height": 720, "width": 1280, "data_size": 2000,
                            },
                            "FPS": 30, "bit_rate": 1000000,
                        }]
                    }
                }
            }

        monkeypatch.setattr(api, "get_video_detail", mock_get_detail)
        result = get_download_info("https://www.douyin.com/video/123")
        assert result["type"] == "video"
        assert result["cdn_url"] == "https://cdn/video.mp4"

    def test_image_note_type(self, monkeypatch):
        from src.douyin import api

        def mock_get_detail(aweme_id):
            return {
                "status_code": 0,
                "aweme_detail": {
                    "images": [{"url_list": ["https://cdn/img.jpg"]}]
                }
            }

        monkeypatch.setattr(api, "get_video_detail", mock_get_detail)
        result = get_download_info("https://www.douyin.com/note/456")
        assert result["type"] == "image_note"
        assert result["image_urls"] == ["https://cdn/img.jpg"]

    def test_api_failure(self, monkeypatch):
        from src.douyin import api

        monkeypatch.setattr(api, "get_video_detail", lambda aweme_id: None)
        result = get_download_info("https://www.douyin.com/video/789")
        assert result["type"] == "error"
        assert result["error"] is not None

    def test_api_status_error(self, monkeypatch):
        from src.douyin import api

        def mock_get_detail(aweme_id):
            return {"status_code": 2, "status_msg": "参数错误"}

        monkeypatch.setattr(api, "get_video_detail", mock_get_detail)
        result = get_download_info("https://www.douyin.com/video/111")
        assert result["type"] == "error"
        assert "2" in result["error"]

    def test_invalid_url(self):
        result = get_download_info("https://www.bilibili.com/video/123")
        assert result["type"] == "error"
        assert "无法从 URL 提取视频 ID" in result["error"]

    def test_no_video_url_in_response(self, monkeypatch):
        from src.douyin import api

        def mock_get_detail(aweme_id):
            return {
                "status_code": 0,
                "aweme_detail": {"video": {"bit_rate": []}}
            }

        monkeypatch.setattr(api, "get_video_detail", mock_get_detail)
        result = get_download_info("https://www.douyin.com/video/222")
        assert result["type"] == "error"
        assert "无法提取视频下载地址" in result["error"]
