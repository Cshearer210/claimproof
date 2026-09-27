"""`python -m claimproof check` -- run every gate over a reply and emit a machine-readable report,
with the two things a checker needs to be adopted into CI: a config that says which gates run, and
an inline comment that silences one.

    check(text, root)   run built-in + plugin gates over `text`; filter by config + suppression
    formats             text (human), json (a script), sarif (GitHub code scanning / a dashboard)
    config              .claimproof.json in cwd (or `root`): {"select": [...], "ignore": [...]} by gate name
    suppression         a line `# claimproof: allow UnbackedClaims` in the reply drops that gate's findings
    plugins             gates registered under the "claimproof.gates" entry point, or a
                        claimproof_plugin_* module exposing GATES = [GateClass, ...]

Gates that need no constructor argument are run as-is; GroundTruth is run against `root` when given,
so a claim's cited files can be checked against the real project. Register/ledger-backed gates are
not part of this text pass -- they answer a different question and have their own entry points.
"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
import re

from claimproof.core import Finding
from claimproof.gates import (UnbackedClaims, ExitCodeMismatch, UnbackedTestCount, GitDiffUnbacked,
                              CIStatusUnbacked, ArtifactNameMismatch, MergeDroppedASide, UnreadSource)
from claimproof.ground_truth import GroundTruth

__all__ = ["all_gates", "check", "to_text", "to_json", "to_sarif", "plugin_errors"]

_BUILTIN = (UnbackedClaims, ExitCodeMismatch, UnbackedTestCount, GitDiffUnbacked, CIStatusUnbacked,
            ArtifactNameMismatch, MergeDroppedASide, UnreadSource)
plugin_errors: list = []


def _plugin_gate_classes():
    out = []
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        group = eps.select(group="claimproof.gates") if hasattr(eps, "select") \
            else eps.get("claimproof.gates", [])
        for ep in group:
            try:
                out.append(ep.load())
            except Exception as exc:
                plugin_errors.append((getattr(ep, "name", str(ep)), repr(exc)))
    except Exception as exc:
        # Announce, never swallow. This was `pass`, so if entry-point discovery itself
        # failed -- a broken installed distribution, an unreadable metadata directory --
        # EVERY plugin gate silently failed to load and `check` still reported on the
        # built-ins alone, looking exactly like a project with no plugins. The two
        # handlers above already record into `plugin_errors`; this one did not, which is
        # the only reason the failure was invisible.
        #
        # Found 2026-09-26 by claimproof's own multi-method scan pointed at this repo
        # (`silent-swallow`, high severity). Discovery is still not aborted -- a missing
        # plugin must not take down the built-in gates -- but the failure is now on the
        # record that callers already read.
        plugin_errors.append(("<entry-point discovery>", repr(exc)))
    for mod in list(pkgutil.iter_modules()):
        if not mod.name.startswith("claimproof_plugin_"):
            continue
        try:
            m = importlib.import_module(mod.name)
            out.extend(getattr(m, "GATES", []) or [])
        except Exception as exc:
            plugin_errors.append((mod.name, repr(exc)))
    return out


def all_gates(root=None):
    """Every gate this text pass runs: built-in text gates + GroundTruth + plugins. Skips any that
    need a constructor argument (those have their own entry points)."""
    gates = []
    for cls in list(_BUILTIN) + _plugin_gate_classes():
        try:
            gates.append(cls())
        except TypeError:
            continue
    gates.append(GroundTruth(root=root) if root else GroundTruth())
    return gates


def _load_config(root):
    p = os.path.join(root or ".", ".claimproof.json")
    if not os.path.exists(p):
        return {"select": None, "ignore": set()}
    try:
        cfg = json.load(open(p, encoding="utf-8"))
        sel = cfg.get("select")
        return {"select": set(sel) if sel else None, "ignore": set(cfg.get("ignore") or [])}
    except (OSError, ValueError):
        return {"select": None, "ignore": set()}


def _suppressed(text, gate_name):
    return bool(re.search(r"#\s*claimproof:\s*(?:allow|ignore)\s+(%s|ALL)\b"
                          % re.escape(gate_name), text, re.I))


def check(text, root=None):
    """Return [(gate_name, Finding)] after config + inline suppression. Reads only."""
    cfg = _load_config(root)
    out = []
    for gate in all_gates(root):
        name = type(gate).__name__
        if cfg["select"] is not None and name not in cfg["select"]:
            continue
        if name in cfg["ignore"] or _suppressed(text, name):
            continue
        try:
            for f in gate.inspect(text):
                out.append((name, f))
        except Exception as exc:
            # A crashing gate must not read as a clean one. This used to be a bare
            # `continue`, so a gate that raised -- a broken plugin, a bad config, a
            # regex blowing up on unusual input -- was skipped in silence and `check`
            # still printed "nothing flagged". Found 2026-09-26 by claimproof's own
            # multi-method scan pointed at this repo (`silent-swallow` at this line),
            # which is the whole argument of the library turned on itself: a checker
            # that cannot look must never report clean (the same law as `ci.UNKNOWN`
            # and `basis.ABSENT`).
            #
            # It still does not abort the run, deliberately: one broken gate taking
            # down every other gate's findings is how a checker gets uninstalled. The
            # failure becomes a FINDING instead, so it is visible in text, JSON and
            # SARIF alike, and the exit code is non-zero exactly as any other finding
            # makes it.
            out.append((name, Finding(
                message=("gate raised %s: %s -- it could not judge this text, so its "
                         "silence is not evidence of anything"
                         % (type(exc).__name__, str(exc)[:160])),
                line=0, excerpt="")))
    return out


def to_text(pairs):
    if not pairs:
        return "claimproof check -- nothing flagged (after config + suppression).\n"
    lines = ["claimproof check -- %d finding(s)" % len(pairs), "=" * 56]
    for name, f in pairs:
        lines.append("  [%s] %s" % (name, f))
    return "\n".join(lines) + "\n"


def to_json(pairs):
    return json.dumps({"tool": "claimproof",
                       "findings": [{"gate": n, "code": n, "message": f.message,
                                     "line": f.line, "excerpt": f.excerpt} for n, f in pairs]},
                      indent=2) + "\n"


def to_sarif(pairs):
    rules = {}
    results = []
    for n, f in pairs:
        rules.setdefault(n, {"id": n, "name": n, "shortDescription": {"text": n}})
        loc = {"physicalLocation": {"artifactLocation": {"uri": "reply"},
                                    "region": {"startLine": f.line or 1}}}
        results.append({"ruleId": n, "level": "warning",
                        "message": {"text": f.message}, "locations": [loc]})
    return json.dumps({"$schema": "https://json.schemastore.org/sarif-2.1.0.json",
                       "version": "2.1.0",
                       "runs": [{"tool": {"driver": {"name": "claimproof",
                                                     "rules": list(rules.values())}},
                                 "results": results}]}, indent=2) + "\n"


def main(argv=None):
    """`claimproof check [file] [--format text|json|sarif] [--root DIR]` (stdin if no file)."""
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    fmt = "text"
    root = None
    files = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--format":
            fmt = argv[i + 1] if i + 1 < len(argv) else "text"; i += 2; continue
        if a.startswith("--format="):
            fmt = a.split("=", 1)[1]; i += 1; continue
        if a == "--root":
            root = argv[i + 1] if i + 1 < len(argv) else None; i += 2; continue
        files.append(a); i += 1
    text = open(files[0], encoding="utf-8").read() if files else sys.stdin.read()
    pairs = check(text, root=root)
    out = {"json": to_json, "sarif": to_sarif}.get(fmt, to_text)(pairs)
    sys.stdout.write(out)
    return 1 if pairs else 0
