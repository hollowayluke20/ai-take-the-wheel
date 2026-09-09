"""Rank-stage tests (ticket 10): hand-computed fixture tables for 02 L172-188.

Fixed clock NOW = 2026-09-09. All expected values below were computed by
hand from the rule; see comments per fixture. Norms are per-component
relative (max in the fixture set = 1).
"""

from datetime import datetime, timedelta, timezone

from attw import cli, rank

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def _iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _cell(value):
    return {
        "value": value,
        "source": "test",
        "as_of": NOW.isoformat(),
        "stale": False,
        "missing": None if value is not None else "source_down",
        "detail": "",
    }


def _cand(name, license_warning=None, **signals):
    return {
        "candidate": name,
        "cells": {key: _cell(value) for key, value in signals.items()},
        "license_warning": license_warning,
    }


def _full(
    *,
    stars,
    push_days,
    release_days,
    issues,
    downloads,
    deps,
    so,
    hn,
    heur_true,
    dependents,
    awesome_count,
    vulns,
):
    flags = {flag: (flag in heur_true) for flag in rank.DOC_FLAGS}
    vuln_list = [{"id": f"CVE-{i}", "severity": sev} for i, sev in enumerate(vulns)]
    return {
        "stars": stars,
        "forks": stars,
        "last_commit_date": _iso(push_days),
        "release_date": _iso(release_days),
        "open_issues": issues,
        "downloads_last_month": downloads,
        "dep_count": deps,
        "so_count": so,
        "hn_count": hn,
        "heuristics": flags,
        "dependents_count": dependents,
        "awesome_hits": {"count": awesome_count, "lists": ["awesome-python"]},
        "vulns": vuln_list,
    }


# Hand computation, fixture set maxes: stars/forks/dl/so/hn/dependents = 99.
# log10(10)/log10(100) = 1/2 = 0.5 exactly; value 99 -> 1.0; value 0 -> 0.0.
# fresh/release: 1/(1+d/180): d=0 -> 1.0, d=180 -> 0.5, d=540 -> 0.25.
# issues: 1/(1+o/100): 0 -> 1.0, 100 -> 0.5, 300 -> 0.25.
ALPHA = _cand(
    "alpha",
    **_full(
        stars=99, push_days=0, release_days=0, issues=0, downloads=99,
        deps=0, so=99, hn=99, heur_true=set(rank.DOC_FLAGS),
        dependents=99, awesome_count=3, vulns=[],
    ),
)
# P0 = mean(1,1,1,1,1) = 1 -> 10. P1 = mean(1,1,1,1) = 1 -> 3.
# P2 = mean(1, min(3/3,1)=1) = 1 -> 1. penalty 0. score = 14.0.
BETA = _cand(
    "beta",
    **_full(
        stars=9, push_days=180, release_days=180, issues=100, downloads=9,
        deps=20, so=9, hn=9, heur_true={"readme"},
        dependents=9, awesome_count=1, vulns=["MEDIUM"],
    ),
)
# P0 = mean(.5,.5,.5,.5,.5) = .5 -> 5. P1 = mean(.5,.5,.5,.2) = .425 -> 1.275.
# P2 = mean(.5, 1/3) = .41667. penalty .5. score = 6.1917.
GAMMA = _cand(
    "gamma",
    **_full(
        stars=0, push_days=540, release_days=540, issues=300, downloads=0,
        deps=80, so=0, hn=0, heur_true=set(),
        dependents=0, awesome_count=0, vulns=["HIGH", "CRITICAL", "MEDIUM"],
    ),
)
# P0 = mean(0,0,.25,.25,.25) = .15 -> 1.5. P1 = mean(.2,0,0,0) = .05 -> .15.
# P2 = 0. raw CVE = 2+2+.5 = 4.5 -> capped 4.0. score = -2.35.


def test_expected_winner_first_with_breakdown():
    result = rank.rank_candidates([BETA, GAMMA, ALPHA], now=NOW)
    names = [entry["name"] for entry in result["ranking"]]
    assert names == ["alpha", "beta", "gamma"]
    by_name = {entry["name"]: entry for entry in result["ranking"]}
    assert by_name["alpha"]["score"] == 14.0
    assert by_name["beta"]["score"] == 6.1917
    assert by_name["gamma"]["score"] == -2.35
    assert by_name["alpha"]["p0"] == 1.0
    assert by_name["beta"]["p1"] == 0.425
    assert by_name["beta"]["norms"]["docs_n"] == 0.2
    assert by_name["beta"]["penalty"] == 0.5
    assert result["verdict"]["decision"] == "recommend"
    assert result["verdict"]["winner"] == "alpha"
    assert result["verdict"]["dissent"] is None  # margin 7.8083, no close call


def test_cve_cap_and_never_veto():
    result = rank.rank_candidates([ALPHA, GAMMA], now=NOW)
    by_name = {entry["name"]: entry for entry in result["ranking"]}
    assert by_name["gamma"]["penalty"] == 4.0  # raw 4.5, capped
    assert by_name["gamma"]["score"] == -2.35  # 1.65 - 4.0, capped not raw
    assert [entry["name"] for entry in result["ranking"]] == ["alpha", "gamma"]


def test_keep_yours_decline():
    incumbent = _cand(
        "incumbent-lib",
        **_full(
            stars=99, push_days=0, release_days=0, issues=0, downloads=99,
            deps=0, so=99, hn=99, heur_true=set(rank.DOC_FLAGS),
            dependents=99, awesome_count=3, vulns=[],
        ),
    )
    weak = _cand(
        "shiny-new",
        **_full(
            stars=9, push_days=180, release_days=180, issues=100, downloads=9,
            deps=20, so=9, hn=9, heur_true={"readme"},
            dependents=9, awesome_count=1, vulns=[],
        ),
    )
    result = rank.rank_candidates([weak], incumbent=incumbent, now=NOW)
    assert result["verdict"]["decision"] == "keep"
    assert result["verdict"]["winner"] is None
    # Challenger beating the incumbent still recommends.
    strong = _cand(
        "clearly-better",
        **_full(
            stars=9999, push_days=0, release_days=0, issues=0,
            downloads=999999, deps=0, so=9999, hn=9999,
            heur_true=set(rank.DOC_FLAGS), dependents=9999,
            awesome_count=3, vulns=[],
        ),
    )
    weak_inc = _cand("legacy-lib", **_full(
        stars=0, push_days=540, release_days=540, issues=300, downloads=0,
        deps=80, so=0, hn=0, heur_true=set(),
        dependents=0, awesome_count=0, vulns=[],
    ))
    result2 = rank.rank_candidates([strong], incumbent=weak_inc, now=NOW)
    assert result2["verdict"]["decision"] == "recommend"
    assert result2["verdict"]["winner"] == "clearly-better"


def test_tie_breaks_by_name_with_dissent():
    base = dict(
        stars=50, push_days=10, release_days=10, issues=10, downloads=5000,
        deps=5, so=50, hn=50, heur_true={"readme", "docs"},
        dependents=50, awesome_count=2, vulns=[],
    )
    first = _cand("zzz-lib", **_full(**base))
    second = _cand("aaa-lib", **_full(**base))
    result = rank.rank_candidates([first, second], now=NOW)
    assert [entry["name"] for entry in result["ranking"]] == ["aaa-lib", "zzz-lib"]
    assert result["ranking"][0]["score"] == result["ranking"][1]["score"]
    assert result["verdict"]["margin"] == 0.0
    assert "aaa-lib" in (result["verdict"]["dissent"] or "")


def test_license_has_zero_numeric_effect():
    kw = dict(
        stars=99, push_days=0, release_days=0, issues=0, downloads=99,
        deps=0, so=99, hn=99, heur_true=set(rank.DOC_FLAGS),
        dependents=99, awesome_count=3, vulns=[],
    )
    mit = _cand("lib-mit", license_warning=None, **_full(**kw))
    gpl = _cand(
        "lib-gpl",
        license_warning="GPL-3.0 mismatch: prose flag only.",
        **_full(**kw),
    )
    result = rank.rank_candidates([gpl, mit], now=NOW)
    scores = {entry["name"]: entry["score"] for entry in result["ranking"]}
    assert scores["lib-mit"] == scores["lib-gpl"] == 14.0
    by_name = {entry["name"]: entry for entry in result["ranking"]}
    assert by_name["lib-gpl"]["license_warning"] == "GPL-3.0 mismatch: prose flag only."
    assert by_name["lib-mit"]["license_warning"] is None


def test_missing_cells_shrink_denominator_confidence_display_only():
    sparse = _cand("sparse", stars=10)  # only signal present in the whole set
    result = rank.rank_candidates([sparse], now=NOW)
    (entry,) = result["ranking"]
    # stars_n = log10(11)/log10(11) = 1.0, sole P0 signal -> P0 = 1.0.
    assert entry["score"] == 10.0  # no confidence multiplier applied
    assert entry["confidence"] == 0.0909  # round(1/11, 4)


# AI-humaniser demo case (ticket 15): 0 stars, no license, not on PyPI
# (no downloads_last_month / release_date cells), zeros elsewhere.
HUMANISER_DEMO = _cand(
    "ai-humaniser-demo",
    license_warning="No license detected.",
    stars=0,
    forks=0,
    so_count=0,
    hn_count=0,
    heuristics={flag: False for flag in rank.DOC_FLAGS},
    awesome_hits={"count": 0, "lists": []},
)
# All norms present-but-zero or missing -> P0/P1/P2 = 0, score 0.0.


def test_floor_declines_weak_addition():
    # Score leg: 3 positive signals but score 1.6667 < floor 2.0.
    stale = _cand(
        "stale-lib",
        last_commit_date=_iso(900),  # fresh 1/(1+5) = 0.1667
        release_date=_iso(900),  # release 0.1667
        open_issues=500,  # issues 1/(1+5) = 0.1667
    )
    result = rank.rank_candidates([stale], now=NOW)
    assert result["ranking"][0]["score"] == 1.6667
    assert result["verdict"]["decision"] == "decline-weak"
    assert result["verdict"]["winner"] is None
    # Signal leg: score 10.0 but a single positive signal.
    lone = _cand("lone-star", stars=10)
    result2 = rank.rank_candidates([lone], now=NOW)
    assert result2["ranking"][0]["score"] == 10.0
    assert result2["verdict"]["decision"] == "decline-weak"
    assert result2["verdict"]["winner"] is None


def test_floor_near_floor_passes():
    # Boundary: score exactly 2.0 with 3 positive signals -> recommend.
    edge = _cand(
        "edge-lib",
        last_commit_date=_iso(720),  # fresh 1/(1+4) = 0.2
        release_date=_iso(720),  # release 0.2
        open_issues=400,  # issues 1/(1+4) = 0.2
    )
    result = rank.rank_candidates([edge], now=NOW)
    assert result["ranking"][0]["score"] == 2.0
    assert result["verdict"]["decision"] == "recommend"
    assert result["verdict"]["winner"] == "edge-lib"
    # Just above with the minimum 2 positive signals -> recommend.
    slim = _cand(
        "slim-lib",
        last_commit_date=_iso(540),  # fresh 0.25
        release_date=_iso(540),  # release 0.25
    )
    result2 = rank.rank_candidates([slim], now=NOW)
    assert result2["ranking"][0]["score"] == 2.5
    assert result2["verdict"]["decision"] == "recommend"
    assert result2["verdict"]["winner"] == "slim-lib"


def test_floor_declines_demo_case():
    result = rank.rank_candidates([HUMANISER_DEMO], now=NOW)
    assert result["ranking"][0]["score"] == 0.0
    assert result["verdict"]["decision"] == "decline-weak"
    assert result["verdict"]["winner"] is None
    # License warning is carried through; it never rescues the score.
    assert result["ranking"][0]["license_warning"] == "No license detected."


def test_floor_skipped_with_incumbent():
    # Below-floor challenger still recommends when it beats the incumbent:
    # the floor applies to additions (no incumbent) only.
    weak_challenger = _cand(
        "stale-but-better",
        last_commit_date=_iso(900),
        release_date=_iso(900),
        open_issues=500,
    )
    legacy = _cand("legacy-lib")  # no cells at all -> score 0.0
    result = rank.rank_candidates([weak_challenger], incumbent=legacy, now=NOW)
    assert result["verdict"]["decision"] == "recommend"
    assert result["verdict"]["winner"] == "stale-but-better"
    # Strong incumbent over a weak challenger stays keep, never decline-weak.
    result2 = rank.rank_candidates([weak_challenger], incumbent=ALPHA, now=NOW)
    assert result2["verdict"]["decision"] == "keep"
    assert result2["verdict"]["winner"] is None


def test_rank_subcommand_reads_candidates_json(tmp_path, capsys):
    import json

    payload = {
        "candidates": [
            {"candidate": entry["candidate"], "cells": entry["cells"]}
            for entry in (GAMMA, BETA, ALPHA)
        ]
    }
    path = tmp_path / "cands.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.main(["rank", str(path)]) == 0
    out = capsys.readouterr().out
    assert out.index("alpha") < out.index("beta") < out.index("gamma")
    assert "verdict: recommend" in out
    # Bare problem string still works (compat shim for analyze).
    assert cli.main(["rank", "CSV parsing"]) == 0
    assert "CSV parsing" in capsys.readouterr().out
