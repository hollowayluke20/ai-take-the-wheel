"""Ticket 13 Part A: verify-harness unit tests (FIXTURE dicts only).

No live network anywhere here: ``run_suite`` tests monkeypatch
``subprocess.run`` with a fake that writes a canned ``pytest-json-report``
file; everything else is pure dict/AST/heartbeat logic over tmp fixtures.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import types

import pytest

from attw import cli, verify
from attw.verify import (
    STALL_SILENCE_S,
    VerifyError,
)

# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------

def _report(entries, exitcode=0, summary=None):
    tests = [{"nodeid": node, "outcome": outcome}
             for node, outcome in entries]
    if summary is None:
        passed = sum(1 for _, o in entries if o == "passed")
        failed = sum(1 for _, o in entries if o in ("failed", "error"))
        summary = {"passed": passed, "failed": failed, "total": len(entries)}
    return {"exitcode": exitcode, "summary": summary, "tests": tests}


def _parsed(entries, exit_code=0, path="baseline.json"):
    rep = _report(entries, exitcode=exit_code)
    return {"outcomes": {n: o for n, o in entries}, "path": path,
            "exit_code": exit_code,
            "summary": rep["summary"], "exitcode": exit_code}


def _fp(**over):
    base = {"python_version": "3.14.0", "pytest_version": "8.4.2",
            "pip_freeze_sha": "abc", "platform": "test",
            "target_git_sha": "deadbee", "authored_tests": [],
            "test_command": "pytest -q"}
    base.update(over)
    return base


def _live_heart():
    return {"present": True, "stalled": False, "reason": "live",
            "path": "verify/heartbeat.jsonl"}


def _build(base_entries, after_entries, **kw):
    args = {"fingerprint": _fp(),
            "baseline": _parsed(base_entries, exit_code=0),
            "after": _parsed(after_entries,
                             exit_code=kw.pop("after_exit", 0),
                             path="after.json"),
            "sandbox_dir": kw.pop("sandbox_dir", None) or
                           tempfile.gettempdir() + "/attw-run1",
            "heartbeat": kw.pop("heartbeat", None) or _live_heart()}
    args.update(kw)
    return verify.build_verify(**args)


# ---------------------------------------------------------------------------
# Diff: all 4 buckets + normalization.
# ---------------------------------------------------------------------------

def test_diff_all_four_buckets():
    baseline = {"a.py::t1": "failed", "a.py::t2": "error",
                "a.py::t3": "passed", "a.py::t4": "passed",
                "a.py::t5": "passed", "a.py::t6": "skipped"}
    after = {"a.py::t1": "passed", "a.py::t2": "passed",
             "a.py::t3": "failed", "a.py::t4": "skipped",
             "a.py::t5": "passed", "a.py::t7": "passed",
             "a.py::t8": "failed"}
    diff = verify.diff_results(baseline, after, {"a.py::t6": "renamed"})
    assert diff["fixed"] == ["a.py::t1", "a.py::t2"]  # fail+error -> pass
    assert sorted(diff["regressed"]) == ["a.py::t3", "a.py::t4"]
    assert diff["new"] == ["a.py::t7", "a.py::t8"]
    assert diff["removed"] == [{"nodeid": "a.py::t6",
                                "reason": "renamed"}]


def test_diff_missing_removed_reason_is_unexplained():
    diff = verify.diff_results({"a.py::t1": "passed"}, {"a.py::t2": "passed"})
    assert diff["removed"] == [{"nodeid": "a.py::t1", "reason": ""}]
    assert verify.decide_verdict(diff, {"a.py::t2": "passed"}) == "fail"


def test_diff_strips_sandbox_prefix():
    baseline = {"C:/Temp/attw-abc/test_x.py::t1": "failed"}
    after = {"test_x.py::t1": "passed"}
    assert verify.diff_results(baseline, after)["fixed"] == ["test_x.py::t1"]


def test_decide_verdict_new_must_pass():
    diff = {"fixed": [], "regressed": [],
            "new": ["n1"], "removed": []}
    assert verify.decide_verdict(diff, {"n1": "failed"}) == "keep-yours"
    assert verify.decide_verdict(diff, {"n1": "passed"}) == "better"


# ---------------------------------------------------------------------------
# Exit codes incl. 5.
# ---------------------------------------------------------------------------

def test_classify_exit_all_codes():
    assert verify.classify_exit(0) == "ok"
    assert verify.classify_exit(1) == "tests-failed"
    assert verify.classify_exit(2) == "interrupted"
    assert verify.classify_exit(3) == "usage-error"
    assert verify.classify_exit(4) == "collection-error"
    assert verify.classify_exit(5) == "no-tests"


def test_gate_exit5_never_passes():
    data = _build([("a.py::t1", "passed")], [("a.py::t1", "passed")],
                  after_exit=5)
    assert data["verdict"] == "fail"
    assert data["gate"]["failed_step"] == 5


def test_gate_exit3_fails():
    data = _build([("a.py::t1", "passed")], [("a.py::t1", "passed")],
                  after_exit=3)
    assert data["verdict"] == "fail"
    assert data["gate"]["failed_step"] == 5


# ---------------------------------------------------------------------------
# run_suite: exact invocation (fake subprocess, no pytest run).
# ---------------------------------------------------------------------------

def _wire_fake_run(monkeypatch, tmp_path, entries, returncode=0):
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        dest = next(t.split("=", 1)[1] for t in cmd
                    if t.startswith("--json-report-file="))
        from pathlib import Path as _P
        _P(dest).parent.mkdir(parents=True, exist_ok=True)
        _P(dest).write_text(json.dumps(_report(entries)), encoding="utf-8")
        return types.SimpleNamespace(returncode=returncode,
                                     stdout="", stderr="")

    monkeypatch.setattr(verify, "_ensure_json_report",
                        lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_run_suite_exact_invocation(tmp_path, monkeypatch):
    entries = [("test_x.py::t1", "passed")]
    calls = _wire_fake_run(monkeypatch, tmp_path, entries)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    path = verify.run_suite(sandbox, "pytest -q tests", label="baseline")
    assert path.name == "baseline.json"
    cmd = calls[0]
    assert cmd[1:3] == ["-m", "pytest"]
    assert "--json-report" in cmd
    assert any(t.startswith("--json-report-file=") for t in cmd)
    assert "-p" in cmd and "no:cacheprovider" in cmd
    assert cmd[-2:] == ["-q", "tests"]  # target args verbatim, no pytest dup
    assert json.loads(path.read_text(encoding="utf-8"))["summary"]["passed"] == 1
    heart = verify.heartbeat_path(sandbox)
    assert heart.is_file()  # run_started + test_node + stage_finished


def test_run_suite_strips_pytest_prefix(tmp_path, monkeypatch):
    _wire_fake_run(monkeypatch, tmp_path, [])
    calls_holder = []
    orig = subprocess.run
    sandbox = tmp_path / "sandbox2"
    sandbox.mkdir()
    verify.run_suite(sandbox, "python -m pytest -q", label="after")
    assert orig is not None and calls_holder == []
    # re-read the recorded command via heartbeat run_started line
    first = (verify.heartbeat_path(sandbox).read_text(
        encoding="utf-8").splitlines()[0])
    assert "python -m pytest -m pytest" not in first


def test_run_suite_missing_sandbox_raises(tmp_path):
    with pytest.raises(VerifyError, match="sandbox not found"):
        verify.run_suite(tmp_path / "missing")


def test_run_suite_timeout_raises_and_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "_ensure_json_report",
                        lambda *a, **k: None)

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, timeout=5)

    monkeypatch.setattr(subprocess, "run", slow)
    sandbox = tmp_path / "sandbox3"
    sandbox.mkdir()
    with pytest.raises(VerifyError, match="timed out"):
        verify.run_suite(sandbox, timeout_s=5)
    assert verify.heartbeat_path(sandbox).is_file()


# ---------------------------------------------------------------------------
# parse_report fixtures.
# ---------------------------------------------------------------------------

def test_parse_report_list_and_dict_formats(tmp_path):
    p1 = tmp_path / "r1.json"
    p1.write_text(json.dumps(_report([("a.py::t1", "passed")],
                                     exitcode=1)), encoding="utf-8")
    parsed = verify.parse_report(p1)
    assert parsed["outcomes"] == {"a.py::t1": "passed"}
    assert parsed["exit_code"] == 1
    p2 = tmp_path / "r2.json"
    p2.write_text(json.dumps({"tests": {"b.py::t2": "failed"}}),
                  encoding="utf-8")
    assert verify.parse_report(p2)["outcomes"] == {"b.py::t2": "failed"}
    with pytest.raises(VerifyError, match="not found"):
        verify.parse_report(tmp_path / "nope.json")


# ---------------------------------------------------------------------------
# Adequacy rules.
# ---------------------------------------------------------------------------

GOOD = ("import demo_target\nimport pytest\n\n"
        "def test_delegatesWheel():\n"
        "    assert demo_target.main(2) == 4\n")


def _write(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return name


def test_adequacy_good_file(tmp_path):
    name = _write(tmp_path, "test_attw_demo.py", GOOD)
    result = verify.check_authored_tests([str(tmp_path / name)])
    assert result == {"ok": True, "reasons": [], "checked": [str(tmp_path / name)]}


def test_adequacy_empty_paths_vacuous():
    assert verify.check_authored_tests([])["ok"] is True


@pytest.mark.parametrize("source,frag", [
    ("import pytest\ndef test_x():\n    assert True\n",
     "constant-only"),
    ("import pytest\ndef test_x():\n    try:\n        f()\n"
     "    except Exception:\n        pass\n",
     "except: pass"),
    ("import pytest\nimport pytest\n@pytest.mark.skip\n"
     "def test_x():\n    assert g() == 1\n",
     "unconditional skip"),
    ("import urllib.request\nimport target\n"
     "def test_x():\n    assert target.f(1) == 1\n",
     "network"),
    ("import pytest\ndef test_x():\n    import random\n"
     "    assert random.random() < 2\n",
     "unseeded"),
    ("import pytest\ndef test_x():\n    assert 1 == 1\n",
     "constant-only"),
])
def test_adequacy_violations(tmp_path, source, frag):
    name = _write(tmp_path, "test_attw_bad.py", source)
    result = verify.check_authored_tests([str(tmp_path / name)])
    assert result["ok"] is False
    assert any(frag in r for r in result["reasons"])


def test_adequacy_bad_filename_and_no_import(tmp_path):
    name = _write(tmp_path, "test_demo.py", GOOD)
    result = verify.check_authored_tests([str(tmp_path / name)])
    assert result["ok"] is False
    assert any("test_attw_" in r for r in result["reasons"])
    lonely = _write(tmp_path, "test_attw_lonely.py",
                    "def test_x():\n    assert True\n")
    result = verify.check_authored_tests([str(tmp_path / lonely)])
    assert result["ok"] is False
    assert any("no imports" in r for r in result["reasons"])


# ---------------------------------------------------------------------------
# Heartbeat + stall.
# ---------------------------------------------------------------------------

def test_heartbeat_append_and_live(tmp_path):
    path = verify.append_heartbeat(tmp_path, "find", "find_candidate", "x")
    assert path.name == "heartbeat.jsonl"
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["stage"] == "find" and line["event"] == "find_candidate"
    assert verify.is_stalled(tmp_path)["stalled"] is False


def test_heartbeat_bad_event_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown heartbeat event"):
        verify.append_heartbeat(tmp_path, "find", "nope")


def test_stall_missing_and_silent(tmp_path):
    assert verify.is_stalled(tmp_path)["stalled"] is True  # missing file
    verify.append_heartbeat(tmp_path, "verify", "run_started")
    old = time.time() - (STALL_SILENCE_S + 60)
    os.utime(verify.heartbeat_path(tmp_path), (old, old))
    status = verify.is_stalled(tmp_path)
    assert status["stalled"] is True
    assert status["silence_s"] > STALL_SILENCE_S


def test_stall_custom_timeout(tmp_path):
    verify.append_heartbeat(tmp_path, "verify", "run_started")
    assert verify.is_stalled(tmp_path, timeout_s=3600)["stalled"] is False


# ---------------------------------------------------------------------------
# Benchmark sub-protocol.
# ---------------------------------------------------------------------------

def test_benchmark_claim_and_overlap():
    bench = {"before": [10.0, 11.0, 10.5, 12.0, 9.8],
             "after": [5.0, 5.5, 4.8, 5.2, 5.1],
             "min_rounds": 5, "warmup": True}
    assert verify.evaluate_benchmark(bench, "measured_gain")["claim"] is True
    overlap = dict(bench, after=[9.0, 9.5, 10.2, 11.0, 10.8])
    claimed = verify.evaluate_benchmark(overlap, "measured_gain")
    assert claimed == {"claim": False,
                       "reason": "distributions overlap — no claim"}


def test_benchmark_guards():
    assert verify.evaluate_benchmark(None)["claim"] is False
    bench = {"before": [10.0] * 5, "after": [5.0] * 5,
             "min_rounds": 5, "warmup": True}
    assert "not measured_gain" in verify.evaluate_benchmark(
        bench, "red_to_green")["reason"]
    assert "min_rounds" in verify.evaluate_benchmark(
        dict(bench, min_rounds=3), "measured_gain")["reason"]
    assert "warmup" in verify.evaluate_benchmark(
        dict(bench, warmup=False), "measured_gain")["reason"]


# ---------------------------------------------------------------------------
# Ordered gate end to end.
# ---------------------------------------------------------------------------

def test_gate_better_via_fixed():
    data = _build([("a.py::t1", "failed")], [("a.py::t1", "passed")])
    assert data["verdict"] == "better"
    assert data["gate"] == {"verdict": "better", "failed_step": None,
                            "reasons": ["steps 1-7 pass"]}


def test_gate_keep_yours_when_no_gain():
    data = _build([("a.py::t1", "passed")], [("a.py::t1", "passed")])
    assert data["verdict"] == "keep-yours"
    assert data["gate"]["failed_step"] is None


def test_gate_regressed_is_step2_killer():
    data = _build([("a.py::t1", "passed"), ("a.py::t2", "failed")],
                  [("a.py::t1", "failed"), ("a.py::t2", "passed")])
    assert data["verdict"] == "fail"
    assert data["gate"]["failed_step"] == 2


def test_gate_keep_yours_mode_with_gains_fails_step3():
    data = _build([("a.py::t1", "failed")], [("a.py::t1", "passed")],
                  mode="keep_yours")
    assert data["verdict"] == "fail"
    assert data["gate"]["failed_step"] == 3


def test_gate_adequacy_fails_step4(tmp_path):
    bad = tmp_path / "test_attw_bad.py"
    bad.write_text("import pytest\ndef test_x():\n    assert True\n",
                   encoding="utf-8")
    data = _build([("a.py::t1", "failed")], [("a.py::t1", "passed")],
                  authored_paths=[str(bad)])
    assert data["verdict"] == "fail"
    assert data["gate"]["failed_step"] == 4


def test_gate_sandbox_violation_fails_step6():
    data = _build([("a.py::t1", "failed")], [("a.py::t1", "passed")],
                  sandbox_dir="C:/repo/target")
    assert data["verdict"] == "fail"
    assert data["gate"]["failed_step"] == 6


def test_gate_stalled_never_passes():
    heart = {"present": True, "stalled": True,
             "reason": "silent 1300s > 1200s"}
    data = _build([("a.py::t1", "failed")], [("a.py::t1", "passed")],
                  heartbeat=heart)
    assert data["verdict"] == "stalled"
    assert data["gate"]["failed_step"] == 7


def test_gate_missing_section_fails_step1():
    gate = verify.evaluate_gate({"fingerprint": {}})
    assert gate == {"verdict": "fail", "failed_step": 1,
                    "reasons": ["step 1: missing verify.json section "
                                "'baseline'"]}


def test_check_sandbox_path():
    assert verify.check_sandbox_path(tempfile.gettempdir() + "/attw-xyz")
    assert verify.check_sandbox_path(tempfile.gettempdir() + "/plain") is True
    assert verify.check_sandbox_path("C:/repo/target") is False


# ---------------------------------------------------------------------------
# check() + write round-trip + CLI wiring.
# ---------------------------------------------------------------------------

def test_check_round_trip_and_cli(tmp_path, capsys):
    data = _build([("a.py::t1", "failed")], [("a.py::t1", "passed")])
    path = verify.write_verify_json(tmp_path / "run" / "verify", data)
    assert path.name == "verify.json"
    out = verify.check(path)
    assert out.startswith("verify: better")
    assert "fixed=1 regressed=0" in out
    assert cli.main(["verify", str(path), "--check"]) == 0
    assert "verify: better" in capsys.readouterr().out


def test_check_fail_json_cli_exit1(tmp_path, capsys):
    data = _build([("a.py::t1", "passed")], [("a.py::t1", "failed")])
    path = verify.write_verify_json(tmp_path / "run2" / "verify", data)
    assert cli.main(["verify", str(path), "--check"]) == 1
    assert "verify: fail" in capsys.readouterr().out


def test_check_missing_file_cli_exit1(capsys):
    assert cli.main(["verify", "no-such-verify.json", "--check"]) == 1
    assert "verify failed" in capsys.readouterr().out
    with pytest.raises(VerifyError, match="not found"):
        verify.check("no-such-verify.json")


def test_fingerprint_shape(tmp_path):
    fp = verify.fingerprint(tmp_path, "pytest -q tests",
                            authored_tests=["test_attw_x.py"])
    assert fp["test_command"] == "pytest -q tests"
    assert fp["authored_tests"] == ["test_attw_x.py"]
    for key in ("python_version", "pytest_version", "pip_freeze_sha",
                "platform", "target_git_sha"):
        assert key in fp
    assert sys.version.split()[0] in fp["python_version"]
