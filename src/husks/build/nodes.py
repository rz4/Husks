"""Node constructors: rule, action, oracle, trial, cond, commit, halt."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from husks.build.site import Store, Node, Recipe, site_path, write_text
from husks.build.identity import _ACTION_ARG_TYPES


# ── Node constructors ─────────────────────────────────────────────

def rule(
    *args: Any,
    name: str | None = None,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    recipe: Recipe = None,
    run: str | None = None,
) -> Node:
    """Construct a rule node.

    The name may be passed positionally or as a keyword::

        rule("greet", child1, child2, ...)   # positional
        rule(child1, child2, :name "greet")  # keyword (Hy style)

    A shell command may be provided via *run* instead of *recipe*::

        rule(:name "gate" :run "husks-gate ..." :outputs ["report.txt"])
    """
    if run is not None and recipe is not None:
        raise TypeError("rule() cannot have both 'run' and 'recipe'")
    children: list[Node] = []
    for a in args:
        if isinstance(a, str):
            if name is not None:
                raise TypeError("rule() got multiple values for 'name'")
            name = a
        elif isinstance(a, dict):
            children.append(a)
        else:
            raise TypeError(f"rule() unexpected argument: {a!r}")
    if name is None:
        raise TypeError("rule() missing required argument: 'name'")
    if run is not None:
        recipe = action(_make_shell_action(run, outputs))
    return {
        "type": "rule",
        "name": name,
        "children": children,
        "inputs": inputs if inputs is not None else [],
        "outputs": outputs if outputs is not None else [],
        "recipe": recipe,
    }


def action(fn: Callable[[Store], None], *args: Any) -> dict[str, Any]:
    """Construct an action recipe from a deterministic callable.

    Extra positional *args* are passed to *fn* after the Store::

        action(my_func, "hello", 42)
        # fn is called as my_func(S, "hello", 42)

    Arguments must be deterministic (str, int, float, bool, bytes, None)
    so that the recipe digest is reproducible.
    """
    for i, a in enumerate(args):
        if not isinstance(a, _ACTION_ARG_TYPES):
            raise TypeError(
                f"action() arg {i + 1} has type {type(a).__name__}; "
                f"only {', '.join(t.__name__ for t in _ACTION_ARG_TYPES)} "
                f"are allowed"
            )
    return {"type": "action", "fn": fn, "args": args}


def _make_shell_action(cmd: str, outputs: list[str] | None = None):
    """Create an action function that runs a shell command.

    The command runs in the site directory.  If the first declared
    output does not yet exist, stdout (and stderr on failure) are
    captured into it.  A nonzero exit code raises RuntimeError,
    which halts the build.
    """
    _outputs = outputs or []

    def shell_action(S: dict) -> None:
        import subprocess as _sp
        from pathlib import Path as _Path

        site = S.get("stage", S["site"])
        live_site = _Path(S["site"])

        # Snapshot live site outputs before running command to enable rollback
        snapshots = {}
        if "stage" in S:
            for o in _outputs:
                live_out = live_site / o
                if live_out.exists():
                    snapshots[o] = live_out.read_bytes()

        # When staging: break symlinks for declared outputs so commands
        # write to stage instead of following symlinks to the live site
        for o in _outputs:
            site_path(S, o, write=True)

        try:
            result = _sp.run(
                cmd,
                shell=True,
                cwd=site,
                capture_output=True,
                text=True,
                timeout=120,
            )
            # Guard: detect symlinks created by command to bypass staging isolation
            if "stage" in S:
                stage_dir = _Path(S["stage"])
                for o in _outputs:
                    out_path = stage_dir / o
                    if out_path.is_symlink():
                        raise RuntimeError(
                            f"shell command created symlink for output '{o}' "
                            f"(staging isolation violation): {cmd}"
                        )
            if _outputs and not Path(site_path(S, _outputs[0], write=True)).exists():
                content = result.stdout
                if result.returncode != 0:
                    content += f"\n--- STDERR (exit {result.returncode}) ---\n"
                    content += result.stderr
                write_text(site_path(S, _outputs[0], write=True), content)
            if result.returncode != 0:
                raise RuntimeError(
                    f"command failed (exit {result.returncode}): {cmd}\n"
                    f"{result.stderr}"
                )
        except Exception:
            # Rollback: restore live site outputs if command failed or violated isolation
            if "stage" in S:
                for o, content in snapshots.items():
                    live_out = live_site / o
                    live_out.write_bytes(content)
            raise

    shell_action._husks_cmd = cmd
    return shell_action


def oracle(
    name: str | None = None,
    *,
    prompt: str = "",
    tools: list[str] | None = None,
    fuel: int = 8,
) -> dict[str, Any]:
    """Construct an oracle recipe."""
    return {
        "type": "oracle",
        "name": name,
        "prompt": prompt,
        "tools": tools if tools is not None else [],
        "fuel": fuel,
    }


def trial(
    *branches: dict[str, Any],
    verdict: Callable | None = None,
) -> dict[str, Any]:
    """Construct a trial recipe from branch recipes."""
    return {
        "type": "trial",
        "branches": list(branches),
        "verdict": verdict,
    }


def cond(
    predicate: Callable[[Store], bool],
    then_node: Node,
    else_node: Node,
) -> Node:
    """Construct a conditional branch node.

    At evaluation time, *predicate* is called with the current Store.
    If it returns True, *then_node* is evaluated; otherwise *else_node*
    is evaluated.  Only one branch fires.

    The predicate is a Python callable, not serializable to JSON.  At
    the IR level, ``kind: "cond"`` references a named predicate that
    the compiler resolves to a callable.
    """
    return {
        "type": "cond",
        "predicate": predicate,
        "then": then_node,
        "else": else_node,
    }


def commit(value: str) -> Node:
    """Construct a commit node."""
    return {"type": "commit", "value": value}


def halt(reason: str) -> Node:
    """Construct a halt node."""
    return {"type": "halt", "reason": reason}
