"""Implement stage: integrate the winning wheel into a sandbox copy (skeleton).

Strategy matrix, manifest order, deletion authority, adapter rules, tidy bar,
sandbox protocol and failure strings per 03 Proposal L108-175. Pure helpers
(manifest choice, adapter placement) are fully implemented; everything that
touches a sandbox copy raises NotImplementedError until the build ticket.
"""

from __future__ import annotations

_SKELETON = "ticket 05 skeleton"

# Manifest edit order, first present wins (03 Proposal L122-124).
_MANIFEST_ORDER = ("pyproject.toml", "setup.cfg", "setup.py")


def choose_manifest(present: list[str]) -> str | None:
    """Pick the manifest to edit from files present in the target.

    Order: pyproject.toml -> setup.cfg -> setup.py (parse only, never
    execute) -> requirements*.txt. Returns None when no manifest found.
    """
    for name in _MANIFEST_ORDER:
        if name in present:
            return name
    reqs = sorted(
        p for p in present if p.startswith("requirements") and p.endswith(".txt")
    )
    return reqs[0] if reqs else None


def adapter_path(layout: str, wheel: str, package: str | None = None) -> str:
    """Adapter file location for one wheel (03 Decision D11).

    Flat-layout target: repo-root `_attw_<wheel>_adapter.py`. Src-layout:
    inside the package (`src/<package>/_attw_<wheel>_adapter.py`).
    """
    filename = f"_attw_{wheel}_adapter.py"
    if layout == "flat":
        return filename
    if layout == "src":
        if not package:
            raise ValueError("src layout needs a package name")
        return f"src/{package}/{filename}"
    raise ValueError(f"Unknown layout: {layout!r} (expected 'flat' or 'src')")


def plan(component: dict, winner: dict, mode: str = "auto") -> dict:
    """Choose the matrix cell (dep-swap / vendor / adapter) for a component.

    mode: auto | addition-only | substitution-only. Skeleton stub.
    """
    _ = (component, winner, mode)
    raise NotImplementedError(f"plan not implemented ({_SKELETON})")


def apply(plan: dict, sandbox_dir: str) -> dict:
    """Apply a plan inside the sandbox copy; return the implement receipt.

    Skeleton stub. Never touches the original target.
    """
    _ = (plan, sandbox_dir)
    raise NotImplementedError(f"apply not implemented ({_SKELETON})")


def snapshot(sandbox_dir: str) -> str:
    """Record a revert snapshot of the sandbox before mutation. Stub."""
    _ = sandbox_dir
    raise NotImplementedError(f"snapshot not implemented ({_SKELETON})")


def revert(sandbox_dir: str, snapshot_id: str) -> None:
    """Restore the sandbox to a snapshot. Skeleton stub."""
    _ = (sandbox_dir, snapshot_id)
    raise NotImplementedError(f"revert not implemented ({_SKELETON})")
