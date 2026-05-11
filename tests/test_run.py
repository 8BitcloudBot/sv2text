import pytest
import logging


def _mock_validate_pass(step):
    pass


def _mock_validate_fail(step):
    raise RuntimeError("缺少 DOUYIN_COOKIE")


class TestRunSteps:

    def test_step_fetch_calls_fetch_all(self, monkeypatch):
        called = {"fetch": False, "process": False}

        import sys
        monkeypatch.setattr(sys, "argv", ["run.py", "--step", "fetch"])
        monkeypatch.setattr("config.setup_logging", lambda name: logging.getLogger(name))

        from run import main
        import run
        monkeypatch.setattr(run, "validate", _mock_validate_pass)
        monkeypatch.setattr(run, "logger", logging.getLogger(__name__))
        monkeypatch.setattr(run, "step_fetch", lambda incremental=False: called.update(fetch=True))
        monkeypatch.setattr(run, "_sync_unprocessed", lambda: called.update(process=True))

        main()

        assert called["fetch"] is True
        assert called["process"] is False

    def test_incremental_passed_to_fetch(self, monkeypatch):
        received = {"incremental": None}

        import sys
        monkeypatch.setattr(sys, "argv", ["run.py", "--step", "fetch", "--incremental"])
        monkeypatch.setattr("config.setup_logging", lambda name: logging.getLogger(name))

        from run import main
        import run
        monkeypatch.setattr(run, "validate", _mock_validate_pass)
        monkeypatch.setattr(run, "logger", logging.getLogger(__name__))
        monkeypatch.setattr(run, "step_fetch", lambda incremental=False: received.update(incremental=incremental))
        monkeypatch.setattr(run, "_sync_unprocessed", lambda: 0)

        main()

        assert received["incremental"] is True

    def test_reanalyze_passed_to_analyze(self, monkeypatch):
        received = {"reanalyze": None}

        import sys
        monkeypatch.setattr(sys, "argv", ["run.py", "--step", "process", "--reanalyze"])
        monkeypatch.setattr("config.setup_logging", lambda name: logging.getLogger(name))

        from run import main
        import run
        monkeypatch.setattr(run, "validate", _mock_validate_pass)
        monkeypatch.setattr(run, "logger", logging.getLogger(__name__))
        monkeypatch.setattr(run, "step_fetch", lambda incremental: None)
        # _sync_unprocessed returns count, then process runs filter→download→analyze
        monkeypatch.setattr(run, "_sync_unprocessed", lambda: 1)
        monkeypatch.setattr(run, "step_filter", lambda incremental=False: None)
        monkeypatch.setattr(run, "step_download", lambda: None)
        monkeypatch.setattr(run, "step_analyze", lambda reanalyze=False: received.update(reanalyze=reanalyze))

        main()

        assert received["reanalyze"] is True

    def test_runtime_error_exits_with_message(self, monkeypatch):
        import sys
        exit_codes = []
        monkeypatch.setattr(sys, "exit", lambda code=0: exit_codes.append(code) or code)
        monkeypatch.setattr(sys, "argv", ["run.py"])
        monkeypatch.setattr("config.setup_logging", lambda name: logging.getLogger(name))

        from run import main
        import run
        monkeypatch.setattr(run, "validate", _mock_validate_fail)
        monkeypatch.setattr(run, "logger", logging.getLogger(__name__))

        main()
        assert 1 in exit_codes

    def test_keyboard_interrupt_exits_130(self, monkeypatch):
        import sys
        exit_codes = []
        monkeypatch.setattr(sys, "exit", lambda code=0: exit_codes.append(code) or code)
        monkeypatch.setattr(sys, "argv", ["run.py"])
        monkeypatch.setattr("config.setup_logging", lambda name: logging.getLogger(name))

        from run import main
        import run
        monkeypatch.setattr(run, "validate", _mock_validate_pass)
        monkeypatch.setattr(run, "logger", logging.getLogger(__name__))
        monkeypatch.setattr(run, "step_fetch", lambda incremental=False: (_ for _ in ()).throw(KeyboardInterrupt()))
        monkeypatch.setattr(run, "_sync_unprocessed", lambda: 0)

        main()
        assert 130 in exit_codes

    def test_all_steps_with_unprocessed(self, monkeypatch):
        called = {"fetch": False, "sync": False, "filter": False, "download": False, "analyze": False}

        import sys
        monkeypatch.setattr(sys, "argv", ["run.py"])
        monkeypatch.setattr("config.setup_logging", lambda name: logging.getLogger(name))

        from run import main
        import run
        monkeypatch.setattr(run, "validate", _mock_validate_pass)
        monkeypatch.setattr(run, "logger", logging.getLogger(__name__))
        monkeypatch.setattr(run, "step_fetch", lambda incremental=False: called.update(fetch=True))
        monkeypatch.setattr(run, "_sync_unprocessed", lambda: called.update(sync=True) or 1)
        monkeypatch.setattr(run, "step_filter", lambda incremental=False: called.update(filter=True))
        monkeypatch.setattr(run, "step_download", lambda: called.update(download=True))
        monkeypatch.setattr(run, "step_analyze", lambda reanalyze=False: called.update(analyze=True))

        main()

        assert called["fetch"] is True
        assert called["filter"] is True
        assert called["download"] is True
        assert called["analyze"] is True
