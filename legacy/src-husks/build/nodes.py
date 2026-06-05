"""Node constructors: rule, action, oracle, trial, cond, commit, halt."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from husks.build.site import Store, Node, Recipe, site_path, write_text
from husks.build.identity import _ACTION_ARG_TYPES
from husks.utils import trace as _T


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
        recipe["cmd"] = run
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
        import selectors as _sel
        from pathlib import Path as _Path

        site = S.get("stage", S["site"])
        live_site = _Path(S["site"])
        rule_name = S.get("_active_rule", "")

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

        # Emit the shell command so the live frame shows what's running.
        if rule_name:
            _T.action_output(rule_name, "tool", f"$ {cmd}")

        try:
            proc = _sp.Popen(
                cmd,
                shell=True,
                cwd=site,
                stdout=_sp.PIPE,
                stderr=_sp.PIPE,
                text=True,
                bufsize=1,  # line-buffered
            )

            # Drain stdout and stderr concurrently, emitting each line as a
            # trace event so the live view can render it beneath the node.
            # selectors avoids the classic two-pipe deadlock without threads
            # and lets us honour a wall-clock deadline.
            out_buf: list[str] = []
            err_buf: list[str] = []
            streams = {
                proc.stdout: ("stdout", out_buf),
                proc.stderr: ("stderr", err_buf),
            }
            selector = _sel.DefaultSelector()
            for pipe in streams:
                selector.register(pipe, _sel.EVENT_READ)

            import time as _time
            deadline = _time.monotonic() + 120
            timed_out = False
            open_pipes = len(streams)
            while open_pipes > 0:
                remaining = deadline - _time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(timeout=min(remaining, 0.5)):
                    pipe = key.fileobj
                    stream_name, buf = streams[pipe]
                    line = pipe.readline()
                    if line == "":  # EOF on this pipe
                        selector.unregister(pipe)
                        open_pipes -= 1
                        continue
                    buf.append(line)
                    if rule_name:
                        _T.action_output(rule_name, stream_name, line)

            if timed_out:
                proc.kill()
                proc.wait()
                selector.close()
                raise _sp.TimeoutExpired(cmd, 120)

            selector.close()
            returncode = proc.wait()
            stdout_text = "".join(out_buf)
            stderr_text = "".join(err_buf)

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
                content = stdout_text
                if returncode != 0:
                    content += f"\n--- STDERR (exit {returncode}) ---\n"
                    content += stderr_text
                write_text(site_path(S, _outputs[0], write=True), content)
            if returncode != 0:
                raise RuntimeError(
                    f"command failed (exit {returncode}): {cmd}\n"
                    f"{stderr_text}"
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
