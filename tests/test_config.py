import pytest
import importlib
import config as config_module


class TestValidate:

    def test_fetch_without_cookie_raises(self, tmp_project, monkeypatch):
        monkeypatch.setenv("DOUYIN_COOKIE", "")
        importlib.reload(config_module)
        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_project)
        with pytest.raises(RuntimeError, match="DOUYIN_COOKIE"):
            config_module.validate("fetch")

    def test_download_without_csv_raises(self, tmp_project, monkeypatch):
        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_project)
        monkeypatch.setattr(config_module, "get_csv_file", lambda: tmp_project / "nonexistent.csv")
        monkeypatch.setattr(config_module, "get_filtered_csv_file", lambda: tmp_project / "no_filter.csv")
        monkeypatch.setattr(config_module, "get_video_dir", lambda: tmp_project / "videos")
        with pytest.raises(RuntimeError, match="CSV 数据文件不存在"):
            config_module.validate("download")

    def test_analyze_without_api_key_raises(self, tmp_project, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "")
        importlib.reload(config_module)
        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_project)
        with pytest.raises(RuntimeError, match="QWEN_API_KEY"):
            config_module.validate("analyze")

    def test_validate_all_checks_fetch_first(self, tmp_project, monkeypatch):
        monkeypatch.setenv("DOUYIN_COOKIE", "")
        monkeypatch.setenv("QWEN_API_KEY", "")
        importlib.reload(config_module)
        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_project)
        with pytest.raises(RuntimeError, match="DOUYIN_COOKIE"):
            config_module.validate("all")

    def test_filter_without_csv_raises(self, tmp_project, monkeypatch):
        monkeypatch.setenv("QWEN_API_KEY", "sk-test")
        importlib.reload(config_module)
        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_project)
        monkeypatch.setattr(config_module, "get_csv_file", lambda: tmp_project / "nonexistent.csv")
        with pytest.raises(RuntimeError, match="CSV 数据文件不存在"):
            config_module.validate("filter")


class TestSetupLogging:

    def test_logger_has_handlers(self, tmp_project, monkeypatch):
        monkeypatch.setattr(config_module, "LOG_DIR", tmp_project / "logs")
        (tmp_project / "logs").mkdir(parents=True, exist_ok=True)
        logger = config_module.setup_logging("test")
        assert len(logger.handlers) == 2
        handler_types = {type(h).__name__ for h in logger.handlers}
        assert "FileHandler" in handler_types
        assert "StreamHandler" in handler_types

    def test_logger_level_is_info(self, tmp_project, monkeypatch):
        monkeypatch.setattr(config_module, "LOG_DIR", tmp_project / "logs")
        (tmp_project / "logs").mkdir(parents=True, exist_ok=True)
        logger = config_module.setup_logging("test2")
        assert logger.level == 20
