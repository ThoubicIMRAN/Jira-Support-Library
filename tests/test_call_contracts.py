"""Every cross-module call must match the real function signature.

A caller passing an argument the callee does not accept (for example the Jira dialog calling
add_comment(idempotency_key=...) before add_comment supported it) fails only when a user clicks
the button, and the error is easy to hide behind a broad ``except``. This test finds it in CI.
"""

import ast
import importlib
import inspect
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("views/", "services/", "utils/", "components/")


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True
    ).stdout.split()
    return [
        f
        for f in out
        if f.startswith(PREFIXES)
        or f in ("app.py", "auth.py", "email_service.py", "oauth_service.py")
    ]


def _signature_problems(fn, call):
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return []
    accepts_kwargs = any(p.kind is p.VAR_KEYWORD for p in params.values())
    bad = [
        k.arg
        for k in call.keywords
        if k.arg and k.arg not in params and not accepts_kwargs
    ]
    star = any(isinstance(a, ast.Starred) for a in call.args) or any(
        k.arg is None for k in call.keywords
    )
    if not star:
        given = {k.arg for k in call.keywords}
        positional = [
            p
            for p in params.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        for i, p in enumerate(positional):
            if p.default is p.empty and i >= len(call.args) and p.name not in given:
                bad.append(f"missing:{p.name}")
        for p in params.values():
            if (
                p.kind is p.KEYWORD_ONLY
                and p.default is p.empty
                and p.name not in given
            ):
                bad.append(f"missing:{p.name}")
        if len(call.args) > len(positional) and not any(
            p.kind is p.VAR_POSITIONAL for p in params.values()
        ):
            bad.append("too_many_positional")
    return bad


def test_call_sites_match_function_signatures():
    problems = []
    for rel in _tracked_files():
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        modules, functions = {}, {}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0]
                in ("services", "utils", "components", "views")
            ):
                for alias in node.names:
                    name = alias.asname or alias.name
                    try:
                        target = importlib.import_module(node.module)
                        obj = getattr(target, alias.name, None)
                        if obj is None:
                            modules[name] = importlib.import_module(
                                f"{node.module}.{alias.name}"
                            )
                        elif inspect.ismodule(obj):
                            modules[name] = obj
                        elif callable(obj) and not inspect.isclass(obj):
                            functions[name] = obj
                    except Exception as exc:  # noqa: BLE001
                        problems.append(
                            f"{rel}:{node.lineno} cannot import {node.module}.{alias.name} ({type(exc).__name__})"
                        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = label = None
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in modules
            ):
                label = f"{node.func.value.id}.{node.func.attr}"
                fn = getattr(modules[node.func.value.id], node.func.attr, None)
                if fn is None:
                    problems.append(f"{rel}:{node.lineno} {label} does not exist")
                    continue
            elif isinstance(node.func, ast.Name) and node.func.id in functions:
                fn, label = functions[node.func.id], node.func.id
            if fn is None or inspect.isclass(fn):
                continue
            bad = _signature_problems(fn, node)
            if bad:
                problems.append(f"{rel}:{node.lineno} {label}({', '.join(bad)})")
    assert not problems, "\n".join(problems)
