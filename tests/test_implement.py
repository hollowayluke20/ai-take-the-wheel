"""Ticket 12: implement-stage applier over LOCAL fixture sandboxes.

No network anywhere here: pip installs, venv creation and the verify
harness capture are all mocked at the module hooks. Tidy runs the real
local `python -m ruff` on touched files (offline-safe).
"""

import json

import pytest

from attw import cli, implement, verify

PASS_REPORT = {"tests": [{"nodeid": "test_demo.py::test_ok", "outcome": "passed"}]}
FAIL_REPORT = {"tests": [{"nodeid": "test_demo.py::test_ok", "outcome": "failed"}]}

PYPROJECT = (
    '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = []\n'
)


def make_repo(root, manifest="pyproject"):
    """Build a tiny flat-layout fixture target."""
    root.mkdir(parents=True, exist_ok=True)
    if manifest in ("pyproject", "both"):
        (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    if manifest in ("requirements", "both"):
        (root / "requirements.txt").write_text("requests\n", encoding="utf-8")
    if manifest == "setup.py":
        (root / "setup.py").write_text(
            "raise RuntimeError('executed!')\n"  # sentinel: parse-only, never run
            "from setuptools import setup\n"
            'setup(name="demo", install_requires=["requests"])\n',
            encoding="utf-8",
        )
    if manifest == "setup.cfg":
        (root / "setup.cfg").write_text(
            "[metadata]\nname = demo\n"
            "[options]\ninstall_requires =\n    requests\n",
            encoding="utf-8",
        )
    (root / "handrolled.py").write_text(
        'def slugify(s):\n    return s.lower().replace(" ", "-")\n',
        encoding="utf-8",
    )
    (root / "test_demo.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    return root


def wire(monkeypatch, tmp_path, reports=None, install="ok"):
    """Mock installs/venv/harness. Returns (pip_calls, suite_calls)."""
    reports = reports or {}
    pip_calls: list[str] = []
    suite_calls: list[str] = []

    def fake_pip(pin, sandbox_dir):
        pip_calls.append(pin)
        if install != "ok":
            raise RuntimeError(f"no wheel {pin}")
        return "installed"

    def fake_suite(sandbox_dir, test_command="pytest -q", label="baseline"):
        suite_calls.append(label)
        path = tmp_path / f"{label}-report.json"
        path.write_text(
            json.dumps(reports.get(label, reports.get("default", PASS_REPORT))),
            encoding="utf-8",
        )
        return path

    monkeypatch.setattr(implement, "_pip_install", fake_pip)
    monkeypatch.setattr(implement, "_ensure_venv", lambda d: {"tool": "mock"})
    monkeypatch.setattr(verify, "run_suite", fake_suite)
    return pip_calls, suite_calls


def dep_swap_plan(**over):
    base = implement.plan(
        {"component": "slug", "kind": "substitution",
         "replaces": ["handrolled.py"]},
        {"wheel": "python-slugify", "version_low": "8.0", "version_high": "9.0"},
    )
    base.update(over)
    return base


# --- matrix cells (03 Proposal section 1) ----------------------------------


def test_plan_addition_maintained_is_dep_swap():
    p = implement.plan({"component": "csv", "kind": "addition"},
                       {"wheel": "pandas"})
    assert (p["kind"], p["strategy"]) == ("addition", "dep-swap")


def test_plan_addition_dead_small_pure_is_vendor():
    p = implement.plan(
        {"component": "x", "kind": "addition"},
        {"wheel": "tiny", "dead": True, "small": True, "pure_python": True},
    )
    assert p["strategy"] == "vendor"


def test_plan_never_vendors_c_extension():
    p = implement.plan(
        {"component": "x", "kind": "addition"},
        {"wheel": "fast", "dead": True, "small": True,
         "pure_python": True, "c_extension": True},
    )
    assert p["strategy"] == "dep-swap"


def test_plan_api_mismatch_is_adapter():
    p = implement.plan({"component": "x", "kind": "addition"},
                       {"wheel": "w", "api_mismatch": True})
    assert p["strategy"] == "adapter"


def test_plan_substitution_carries_deletes():
    p = implement.plan(
        {"component": "slug", "kind": "substitution",
         "replaces": ["handrolled.py"]},
        {"wheel": "python-slugify"},
    )
    assert p["strategy"] == "dep-swap" and p["delete"] == ["handrolled.py"]


def test_plan_gpl_forces_dep_swap_or_skip():
    p = implement.plan(
        {"component": "x", "kind": "addition"},
        {"wheel": "gpl-lib", "license": "GPL-3.0",
         "dead": True, "small": True, "pure_python": True},
    )
    assert p["strategy"] == "dep-swap" and p["license_warning"]


def test_plan_modes_and_bad_mode():
    add = implement.plan({"component": "x"}, {"wheel": "w"},
                         mode="addition-only")
    sub = implement.plan({"component": "x"}, {"wheel": "w"},
                         mode="substitution-only")
    assert (add["kind"], sub["kind"]) == ("addition", "substitution")
    with pytest.raises(ValueError, match="mode"):
        implement.plan({}, {}, mode="sideways")


def test_plan_pin_form():
    p = implement.plan({"component": "x"}, {"wheel": "w", "version_low": "1.0",
                                            "version_high": "2.0"})
    assert p["pin"] == "w>=1.0,<2.0"


# --- manifest order + pins ---------------------------------------------------


def test_apply_dep_swap_prefers_pyproject(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb", manifest="both")
    wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(), str(sandbox))
    assert receipt["ok"] and receipt["manifest"] == "pyproject.toml"
    assert "python-slugify>=8.0,<9.0" in receipt["manifest_diff"]
    assert "python-slugify" not in (sandbox / "requirements.txt").read_text()


def test_apply_requirements_pin(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb", manifest="requirements")
    wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(), str(sandbox))
    assert receipt["ok"] and receipt["manifest"] == "requirements.txt"
    assert "python-slugify>=8.0,<9.0" in (sandbox / "requirements.txt").read_text()


def test_apply_setup_py_parse_only(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb", manifest="setup.py")
    wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(delete=[]), str(sandbox))
    assert receipt["ok"] and receipt["manifest"] == "setup.py"
    text = (sandbox / "setup.py").read_text(encoding="utf-8")
    assert "python-slugify>=8.0,<9.0" in text  # edited as text, never executed
    assert "RuntimeError('executed!')" in text  # sentinel intact


def test_apply_setup_cfg(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb", manifest="setup.cfg")
    wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(delete=[]), str(sandbox))
    assert receipt["ok"]
    assert "python-slugify>=8.0,<9.0" in (sandbox / "setup.cfg").read_text()


# --- delete / adapter / revert / sandbox ------------------------------------


def test_apply_delete_records_and_removes(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(), str(sandbox))
    assert receipt["ok"]
    assert receipt["deleted_paths"] == ["handrolled.py"]
    assert not (sandbox / "handrolled.py").exists()
    assert receipt["manifest_diff"] and receipt["snapshot"]


def test_apply_adapter_is_delegation_only(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path)
    p = implement.plan(
        {"component": "slug", "kind": "addition"},
        {"wheel": "python-slugify", "api_mismatch": True,
         "adapter_funcs": ["slugify"]},
    )
    receipt = implement.apply(p, str(sandbox))
    assert receipt["ok"]
    rel = receipt["adapter_path"]
    assert rel == "_attw_python-slugify_adapter.py"
    source = (sandbox / rel).read_text(encoding="utf-8")
    compile(source, rel, "exec")
    assert implement.is_delegation_only(source)
    assert "python_slugify" in source


def test_apply_adapter_has_no_loc_cap(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path)
    funcs = [f"fn_{i}" for i in range(60)]
    p = implement.plan(
        {"component": "slug", "kind": "addition"},
        {"wheel": "big", "api_mismatch": True, "adapter_funcs": funcs},
    )
    receipt = implement.apply(p, str(sandbox))
    assert receipt["ok"]  # 60 wrappers accepted: NO loc cap per ruling


def test_is_delegation_only_rejects_logic():
    assert not implement.is_delegation_only(
        "import w as _wheel_mod\n"
        "def f(*a, **k):\n"
        "    x = _wheel_mod.f(*a, **k)\n"
        "    return x.strip()\n"
    )


def test_snapshot_revert_round_trip(tmp_path):
    sandbox = make_repo(tmp_path / "sb")
    snap = implement.snapshot(str(sandbox))
    (sandbox / "handrolled.py").write_text("MUTATED\n", encoding="utf-8")
    (sandbox / "extra.py").write_text("x = 1\n", encoding="utf-8")
    implement.revert(str(sandbox), snap)
    assert "slugify" in (sandbox / "handrolled.py").read_text()
    assert not (sandbox / "extra.py").exists()


def test_original_never_touched(tmp_path, monkeypatch):
    original = make_repo(tmp_path / "orig")
    before = (original / "pyproject.toml").read_text(encoding="utf-8")
    sandbox = implement.make_sandbox(original)
    assert sandbox.startswith(str(tmp_path)) or "attw-" in sandbox
    wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(), sandbox)
    assert receipt["ok"]
    assert (original / "pyproject.toml").read_text() == before
    assert (original / "handrolled.py").exists()  # delete stayed in sandbox


def test_prefix_assert_blocks_escape(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="outside sandbox"):
        implement.apply(dep_swap_plan(delete=["../escape.txt"]), str(sandbox))
    assert not (tmp_path / "escape.txt").exists()


# --- failure strings (exact `implement: <code>`) ------------------------------


def test_failed_install_after_two_fallbacks(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    pip_calls, _ = wire(monkeypatch, tmp_path, install="boom")
    p = dep_swap_plan()
    p["fallbacks"] = ["fb1", "fb2", "fb3-ignored"]
    receipt = implement.apply(p, str(sandbox))
    assert not receipt["ok"]
    assert receipt["failure_string"] == "implement: failed-install"
    assert receipt["failure"]["code"] == "failed-install"
    assert pip_calls == ["-e .", p["pin"], "fb1", "fb2"]
    # target editable, then 2 fallbacks, then stop
    assert "python-slugify" not in (sandbox / "pyproject.toml").read_text()


def test_api_mismatch_reverts_single_attempt(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    before = (sandbox / "pyproject.toml").read_text(encoding="utf-8")
    pip_calls, _ = wire(monkeypatch, tmp_path)
    p = implement.plan(
        {"component": "slug", "kind": "addition"},
        {"wheel": "odd", "api_mismatch": True,
         "adapter_funcs": ["go"], "adapter_valid": False},
    )
    receipt = implement.apply(p, str(sandbox))
    assert receipt["failure_string"] == "implement: api-mismatch"
    assert receipt["reverted"] is True
    assert len(pip_calls) == 2
    # target editable + one adapter attempt, no install retries
    assert (sandbox / "pyproject.toml").read_text() == before
    assert not (sandbox / "_attw_odd_adapter.py").exists()


def test_regression_reverts(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path,
         reports={"baseline": PASS_REPORT, "after": FAIL_REPORT,
                  "default": PASS_REPORT})
    receipt = implement.apply(dep_swap_plan(), str(sandbox))
    assert receipt["failure_string"] == "implement: regression"
    assert receipt["reverted"] is True
    assert (sandbox / "handrolled.py").exists()  # delete reverted


# --- harness boundary + tidy/typecheck ---------------------------------------


def test_calls_harness_capture_for_baseline_and_after(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    _, suite_calls = wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(delete=[]), str(sandbox))
    assert receipt["ok"]
    assert suite_calls == ["baseline", "after"]
    assert receipt["baseline_nodes"] == 1 and receipt["after_nodes"] == 1


def test_tidy_and_typecheck_recorded(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path)
    p = implement.plan(
        {"component": "slug", "kind": "addition"},
        {"wheel": "python-slugify", "api_mismatch": True,
         "adapter_funcs": ["slugify"]},
    )
    receipt = implement.apply(p, str(sandbox))
    assert receipt["ok"]
    assert set(receipt["tidy"]) >= {"check", "format", "ok"}
    assert receipt["tidy"]["ok"] is True  # real local ruff, clean adapter
    assert receipt["typecheck"]["ok"] is True  # advisory-only, never a gate


# --- vendor branch (03 Proposal section 1) --------------------------------------


def vendor_plan(**over):
    p = implement.plan(
        {"component": "x", "kind": "addition"},
        {"wheel": "tiny", "dead": True, "small": True, "pure_python": True,
         "version_low": "1.0", "license": "MIT",
         "vendor_source": {
             "__init__.py": "VALUE = 1\n",
             "core.py": "import tiny\nVALUE2 = 2\n",
         }},
    )
    assert p["strategy"] == "vendor"
    p.update(over)
    return p


def test_apply_vendor_creates_vendored_tree(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    (sandbox / "uses_tiny.py").write_text(
        "import tiny\nfrom tiny import VALUE\n", encoding="utf-8"
    )
    wire(monkeypatch, tmp_path)
    receipt = implement.apply(vendor_plan(), str(sandbox))
    assert receipt["ok"] and receipt["strategy"] == "vendor"
    vdir = sandbox / "_vendored" / "tiny"
    assert (vdir / "__init__.py").is_file()
    assert (vdir / "core.py").is_file()
    assert "_vendored.tiny" in (vdir / "core.py").read_text(encoding="utf-8")
    assert "import tiny\n" not in (vdir / "core.py").read_text(encoding="utf-8")
    attr = vdir / "ATTRIBUTION"
    assert attr.is_file()
    text = attr.read_text(encoding="utf-8")
    assert "tiny" in text and "1.0" in text
    assert "https://pypi.org/project/tiny/" in text and "MIT" in text
    site = (sandbox / "uses_tiny.py").read_text(encoding="utf-8")
    assert "_vendored.tiny" in site  # call-site imports rewritten
    assert "tiny>=1.0" in receipt["notes"]  # pin in notes
    assert "tiny>=1.0" in (sandbox / "pyproject.toml").read_text()


def test_apply_vendor_refuses_c_extension(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path)
    p = vendor_plan()
    p["c_extension"] = True  # stale plan claims vendor for a C-ext wheel
    p["strategy"] = "vendor"
    receipt = implement.apply(p, str(sandbox))
    assert receipt["ok"] and receipt["strategy"] == "dep-swap"
    assert not (sandbox / "_vendored").exists()
    assert "C-extension" in receipt["notes"]


def test_apply_vendor_gpl_stays_dep_swap(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path)
    p = vendor_plan()
    p["license"] = "GPL-3.0"  # stale vendor plan over GPL code
    p["strategy"] = "vendor"
    receipt = implement.apply(p, str(sandbox))
    assert receipt["ok"] and receipt["strategy"] == "dep-swap"
    assert not (sandbox / "_vendored").exists()


# --- CLI wiring ----------------------------------------------------------------


def test_cli_implement_success_and_failure(tmp_path, monkeypatch, capsys):
    sandbox = make_repo(tmp_path / "sb")
    wire(monkeypatch, tmp_path)
    args = ["implement", "--component", "slug", "--wheel", "python-slugify",
            "--sandbox-dir", str(sandbox)]
    assert cli.main(args) == 0
    assert '"ok": true' in capsys.readouterr().out
    args[-1] = str(tmp_path / "missing")
    assert cli.main(args) == 1
    assert "implement: failed-install" in capsys.readouterr().out


# --- target-deps-before-baseline + suite-target threading ---------------------


def test_target_deps_installed_before_winner(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb", manifest="both")
    pip_calls, _ = wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(delete=[]), str(sandbox))
    assert receipt["ok"]
    assert pip_calls[:3] == ["-e .", "-r requirements.txt", dep_swap_plan()["pin"]]
    assert receipt["target_deps"]["installed"] == [
        "-e .", "-r requirements.txt",
    ]
    assert receipt["target_deps"]["failures"] == []


def test_target_deps_failure_records_never_raise(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb", manifest="both")
    wire(monkeypatch, tmp_path, install="boom")
    p = dep_swap_plan(delete=[])
    receipt = implement.apply(p, str(sandbox))
    assert not receipt["ok"]  # winner install still fails exactly
    assert receipt["failure"]["code"] == "failed-install"
    deps = receipt["target_deps"]
    assert deps["installed"] == [] and len(deps["failures"]) == 2
    assert all(
        f["stage"] == "implement" and f["code"] == "failed-install"
        for f in deps["failures"]
    )


def test_detect_test_command_prefers_suite_dir(tmp_path):
    assert implement._detect_test_command(str(tmp_path)) == "pytest -q"
    (tmp_path / "tests").mkdir()
    assert implement._detect_test_command(str(tmp_path)) == "pytest -q tests"
    (tmp_path / "tests").rmdir()
    (tmp_path / "test").mkdir()
    assert implement._detect_test_command(str(tmp_path)) == "pytest -q test"


def test_apply_threads_test_command_to_harness(tmp_path, monkeypatch):
    import json as _json

    sandbox = make_repo(tmp_path / "sb")
    seen: list[tuple[str, str]] = []

    def fake_suite(sandbox_dir, test_command="pytest -q", label="baseline"):
        seen.append((label, test_command))
        path = tmp_path / f"{label}-report.json"
        path.write_text(_json.dumps(PASS_REPORT), encoding="utf-8")
        return path

    monkeypatch.setattr(verify, "run_suite", fake_suite)
    monkeypatch.setattr(implement, "_pip_install", lambda pin, d: "installed")
    monkeypatch.setattr(implement, "_ensure_venv", lambda d: {"tool": "mock"})
    receipt = implement.apply(
        dep_swap_plan(delete=[]), str(sandbox), "pytest -q tests"
    )
    assert receipt["ok"]
    assert seen == [("baseline", "pytest -q tests"), ("after", "pytest -q tests")]
    assert receipt["test_command"] == "pytest -q tests"


# --- pytest plugin deps from target config (key 30: --cov needs pytest-cov) -


def test_pytest_plugin_pins_cov_string_addopts(tmp_path):
    sb = tmp_path / "sb"
    sb.mkdir()
    (sb / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        '[tool.pytest.ini_options]\n'
        'addopts = "-vvv --cov-report term-missing --cov=cookiecutter"\n',
        encoding="utf-8",
    )
    assert implement._pytest_plugin_pins(str(sb)) == ["pytest-cov"]


def test_pytest_plugin_pins_cov_list_addopts_and_setup_cfg(tmp_path):
    sb = tmp_path / "sb"
    sb.mkdir()
    (sb / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        '[tool.pytest.ini_options]\n'
        'addopts = ["-q", "--cov=demo"]\n',
        encoding="utf-8",
    )
    assert implement._pytest_plugin_pins(str(sb)) == ["pytest-cov"]
    sb2 = tmp_path / "sb2"
    sb2.mkdir()
    (sb2 / "setup.cfg").write_text(
        "[tool:pytest]\naddopts = --cov=demo --cov-report term-missing\n",
        encoding="utf-8",
    )
    assert implement._pytest_plugin_pins(str(sb2)) == ["pytest-cov"]


def test_pytest_plugin_pins_p_allowlist_no_and_unknown(tmp_path):
    sb = tmp_path / "sb"
    sb.mkdir()
    (sb / "pytest.ini").write_text(
        "[pytest]\naddopts = -p pytest_mock -p no:cacheprovider -p some_evil_pkg\n",
        encoding="utf-8",
    )
    assert implement._pytest_plugin_pins(str(sb)) == ["pytest-mock"]


def test_target_deps_installs_pytest_plugin_pins(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    (sandbox / "pyproject.toml").write_text(
        PYPROJECT + '[tool.pytest.ini_options]\naddopts = "--cov=demo"\n',
        encoding="utf-8",
    )
    pip_calls, _ = wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(delete=[]), str(sandbox))
    assert receipt["ok"]
    assert pip_calls[:2] == ["-e .", "pytest-cov"]
    assert "-e ." in receipt["target_deps"]["installed"]
    assert "pytest-cov" in receipt["target_deps"]["installed"]


def test_target_deps_plugin_failure_records_never_raises(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    (sandbox / "pyproject.toml").write_text(
        PYPROJECT + '[tool.pytest.ini_options]\naddopts = "--cov=demo"\n',
        encoding="utf-8",
    )

    def fake_pip(pin, sandbox_dir):
        if pin == "pytest-cov":
            raise RuntimeError("no wheel pytest-cov")
        return "installed"

    monkeypatch.setattr(implement, "_pip_install", fake_pip)
    monkeypatch.setattr(implement, "_ensure_venv", lambda d: {"tool": "mock"})
    rec = implement._install_target_deps(str(sandbox), "slug")
    assert rec["installed"] == ["-e ."]
    assert len(rec["failures"]) == 1
    assert rec["failures"][0]["code"] == "failed-install"


# --- TEST dependency-groups (ticket 14: key 30 needs freezegun) -----------


def test_test_group_pins_dependency_groups_only_test(tmp_path):
    sb = tmp_path / "sb"
    sb.mkdir()
    (sb / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        "[dependency-groups]\n"
        'test = ["pytest", "pytest-cov", "pytest-mock", "freezegun"]\n'
        'dev = ["sphinx"]\n'
        'docs = ["sphinx"]\n'
        'lint = ["ruff"]\n',
        encoding="utf-8",
    )
    pins = implement._test_group_pins(str(sb))
    assert pins == ["pytest", "pytest-cov", "pytest-mock", "freezegun"]


def test_test_group_pins_include_group_and_unknown_tables(tmp_path):
    sb = tmp_path / "sb"
    sb.mkdir()
    (sb / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        "[dependency-groups]\n"
        'test = [{include-group = "shared"}, "freezegun", {other = 1}, 42]\n'
        'shared = ["pytest-mock"]\n',
        encoding="utf-8",
    )
    pins = implement._test_group_pins(str(sb))
    assert pins == ["pytest-mock", "freezegun"]
    # missing/unparseable files yield [], never raise
    assert implement._test_group_pins(str(tmp_path / "missing")) == []
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "pyproject.toml").write_text("not = [valid toml", encoding="utf-8")
    assert implement._test_group_pins(str(bad)) == []


def test_test_group_pins_setup_cfg_extras(tmp_path):
    sb = tmp_path / "sb"
    sb.mkdir()
    (sb / "setup.cfg").write_text(
        "[metadata]\nname = demo\n"
        "[options.extras_require]\n"
        "test =\n"
        "    freezegun\n"
        "    pytest-mock\n"
        "docs =\n"
        "    sphinx\n",
        encoding="utf-8",
    )
    assert implement._test_group_pins(str(sb)) == ["freezegun", "pytest-mock"]


def test_test_group_pins_setup_py_extras_parse_only(tmp_path):
    sb = tmp_path / "sb"
    sb.mkdir()
    (sb / "setup.py").write_text(
        "raise RuntimeError('executed!')\n"  # sentinel: parse-only, never run
        "from setuptools import setup\n"
        "setup(name='demo', extras_require="
        "{'test': ['freezegun'], 'docs': ['sphinx']})\n",
        encoding="utf-8",
    )
    assert implement._test_group_pins(str(sb)) == ["freezegun"]


def test_test_group_pins_requirements_files(tmp_path):
    sb = tmp_path / "sb"
    sb.mkdir()
    (sb / "requirements-test.txt").write_text("freezegun\n", encoding="utf-8")
    (sb / "requirements-dev.txt").write_text("sphinx\n", encoding="utf-8")
    (sb / "requirements").mkdir()
    (sb / "requirements" / "test-extra.txt").write_text(
        "pytest-mock\n", encoding="utf-8"
    )
    (sb / "requirements" / "prod.txt").write_text("requests\n", encoding="utf-8")
    pins = implement._test_group_pins(str(sb))
    assert "-r requirements-test.txt" in pins
    assert "-r requirements/test-extra.txt" in pins
    assert not any("dev" in p or "prod" in p for p in pins)


def test_target_deps_installs_test_groups_cookiecutter_shape(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    (sandbox / "pyproject.toml").write_text(
        PYPROJECT
        + "[dependency-groups]\n"
        + 'test = ["pytest", "pytest-cov", "pytest-mock", "freezegun"]\n'
        + '[tool.pytest.ini_options]\naddopts = "--cov=demo"\n',
        encoding="utf-8",
    )
    pip_calls, _ = wire(monkeypatch, tmp_path)
    receipt = implement.apply(dep_swap_plan(delete=[]), str(sandbox))
    assert receipt["ok"]
    # editable, then pytest-cov once (plugin + group deduped), then the rest
    assert pip_calls[0] == "-e ."
    assert pip_calls.count("pytest-cov") == 1
    assert "freezegun" in pip_calls and "pytest-mock" in pip_calls
    installed = receipt["target_deps"]["installed"]
    assert "freezegun" in installed and "pytest-mock" in installed
    assert receipt["target_deps"]["failures"] == []


def test_target_deps_test_group_failure_records_never_raise(tmp_path, monkeypatch):
    sandbox = make_repo(tmp_path / "sb")
    (sandbox / "pyproject.toml").write_text(
        PYPROJECT + "[dependency-groups]\ntest = [\"freezegun\"]\n",
        encoding="utf-8",
    )

    def fake_pip(pin, sandbox_dir):
        if pin == "freezegun":
            raise RuntimeError("no wheel freezegun")
        return "installed"

    monkeypatch.setattr(implement, "_pip_install", fake_pip)
    monkeypatch.setattr(implement, "_ensure_venv", lambda d: {"tool": "mock"})
    rec = implement._install_target_deps(str(sandbox), "slug")
    assert rec["installed"] == ["-e ."]
    assert len(rec["failures"]) == 1
    failure = rec["failures"][0]
    assert failure["stage"] == "implement"
    assert failure["code"] == "failed-install"
    assert "freezegun" in failure["reason"]
