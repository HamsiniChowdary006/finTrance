from __future__ import annotations

import subprocess
from pathlib import Path

import run_demo


def test_parser_supports_launcher_flags():
    args = run_demo.parser().parse_args(["--ticker", "T", "--peers", "A,B", "--synthetic",
                                         "--time-budget", "4"])
    assert args.ticker == "T"
    assert args.peers == "A,B"
    assert args.synthetic is True
    assert args.time_budget == 4


def test_dry_run_has_no_side_effects(capsys, monkeypatch):
    monkeypatch.setattr(run_demo, "preflight", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("preflight should not run")))
    assert run_demo.main(["--dry-run"]) == 0
    assert "Plan:" in capsys.readouterr().out


def test_folder_discovery(tmp_path, monkeypatch):
    (tmp_path / "B").mkdir()
    (tmp_path / "A").mkdir()
    (tmp_path / "ignored.txt").write_text("x")
    monkeypatch.setattr(run_demo, "MANUAL_ROOT", tmp_path)
    assert run_demo.discover_folders() == ["A", "B"]


def test_universe_parsing_and_fallback(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "universe.csv").write_text("ticker,name,type,peers\nA,Alpha,bank,B\n",
                                        encoding="utf-8")
    monkeypatch.setattr(run_demo, "REPO_ROOT", tmp_path)
    assert run_demo.read_universe()["A"]["name"] == "Alpha"
    assert run_demo.read_universe()["A"]["peers"] == ["B"]
    (data / "universe.csv").unlink()
    assert run_demo.read_universe() == {}


def test_company_selection_infers_same_type_peers(monkeypatch):
    monkeypatch.setattr(run_demo, "read_universe", lambda: {
        "A": {"name": "A", "type": "bank", "peers": []},
        "B": {"name": "B", "type": "bank", "peers": []},
    })
    monkeypatch.setattr(run_demo, "discover_folders", lambda: ["A", "B"])
    args = run_demo.parser().parse_args(["--all"])
    assert run_demo.choose_companies(args)[0][2] == ["B"]


def test_empty_drop_is_actionable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_demo, "MANUAL_ROOT", tmp_path)
    monkeypatch.setattr(run_demo, "preflight", lambda: None)
    monkeypatch.setattr(run_demo, "load_environment", lambda: None)
    assert run_demo.main(["--no-app"]) == 1
    output = capsys.readouterr().out
    assert "store/manual_drop" in output
    assert "--synthetic" in output


def test_synthetic_fixture_is_labelled(tmp_path):
    from store.dao import EvidenceStore

    store = EvidenceStore(tmp_path / "evidence.sqlite")
    run_demo.create_synthetic(store)
    document = store.documents_for("SYNTHETIC")[0]
    assert "SYNTHETIC" in document.title
    assert all("SYNTHETIC" in fact.quote for fact in store.facts_for("SYNTHETIC"))


def test_busy_port_selects_next_port(monkeypatch):
    import socket
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    port = occupied.getsockname()[1]
    try:
        assert run_demo.free_port(port) != port
    finally:
        occupied.close()


def test_check_order_and_stop_on_failure(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1 if len(calls) == 2 else 0)

    monkeypatch.setattr(run_demo.subprocess, "run", fake_run)
    assert run_demo.run_checks() == 1
    assert len(calls) == 2
    assert calls[0][2] == "pytest"
    assert calls[1][2] == "ruff"


def test_check_subprocesses_are_argument_lists(monkeypatch):
    calls = []
    monkeypatch.setattr(run_demo.subprocess, "run",
                        lambda command, **kwargs: calls.append((command, kwargs))
                        or subprocess.CompletedProcess(command, 0))
    assert run_demo.run_checks() == 0
    assert all(isinstance(command, list) for command, _ in calls)
    assert all(kwargs.get("shell", False) is False for _, kwargs in calls)


def test_no_key_is_printed(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-secret-key")
    monkeypatch.setattr(run_demo, "REPO_ROOT", Path("."))
    run_demo.load_environment()
    output = capsys.readouterr().out
    assert "fake-secret-key" not in output


def test_preflight_does_not_install_when_imports_exist(monkeypatch):
    calls = []
    monkeypatch.setattr(run_demo, "dependencies_ready", lambda: True)
    monkeypatch.setattr(run_demo.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    run_demo.preflight()
    assert calls == []


def test_preflight_install_uses_pip_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(run_demo, "dependencies_ready", lambda: False)
    monkeypatch.setattr(run_demo.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    run_demo.preflight()
    assert calls[0][0][0][0:4] == [run_demo.sys.executable, "-m", "pip", "install"]
    assert calls[0][1].get("shell", False) is False


def test_partial_failure_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(run_demo, "preflight", lambda: None)
    monkeypatch.setattr(run_demo, "load_environment", lambda: None)
    monkeypatch.setattr(run_demo, "choose_companies", lambda args: [("A", "A", [], "bank"),
                                                                      ("B", "B", [], "bank")])
    monkeypatch.setattr(run_demo, "run_company",
                        lambda ticker, *args, **kwargs: (_ for _ in ()).throw(
                            RuntimeError("fixture failure")) if ticker == "A" else {
                                "company": "B", "type": "configured", "facts": 0, "quarters": 0,
                                "strength": "Weak", "discovery": "none", "runtime": 0,
                                "warnings": []})
    assert run_demo.main(["--no-app"]) == 1
    assert "Failures" in capsys.readouterr().out


def test_port_argument_is_preserved():
    args = run_demo.parser().parse_args(["--port", "9000"])
    assert args.port == 9000


def test_no_app_skips_launch(monkeypatch):
    monkeypatch.setattr(run_demo, "preflight", lambda: None)
    monkeypatch.setattr(run_demo, "load_environment", lambda: None)
    monkeypatch.setattr(run_demo, "choose_companies", lambda args: [("A", "A", [], "bank")])
    monkeypatch.setattr(run_demo, "run_company", lambda *args, **kwargs: {
        "company": "A", "type": "configured", "facts": 0, "quarters": 0,
        "strength": "Weak", "discovery": "none", "runtime": 0, "warnings": []})
    monkeypatch.setattr(run_demo, "launch_app", lambda *args: (_ for _ in ()).throw(
        AssertionError("app should not launch")))
    assert run_demo.main(["--no-app"]) == 0
