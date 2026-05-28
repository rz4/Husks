"""build package — public re-exports preserving existing import paths."""

from husks.build.site import (
    Store,
    Node,
    Recipe,
    OracleBackend,
    Stop,
    site_path,
    ensure_dir,
    read_text,
    write_text,
    file_exists,
    fresh_store,
    burn,
    file_sig,
)
from husks.build.identity import (
    _fn_behavior_digest,
    _pred_identity,
    VERDICT_POLICIES,
    recipe_to_cse,
    _ACTION_ARG_TYPES,
)
from husks.build.seal import (
    compute_cse_seal,
    seal_file,
    read_seal,
    output_hashes,
    freshness_check,
    write_seal,
    history_file,
    append_history,
    write_trial_report,
    write_build_manifest,
    _collect_rules,
)
from husks.build.nodes import (
    rule,
    action,
    _make_shell_action,
    oracle,
    trial,
    cond,
    commit,
    halt,
)
from husks.build.eval import (
    _check_declared_outputs,
    eval_node,
    eval_cond,
    eval_rule,
    eval_recipe,
    default_oracle_backend,
    eval_oracle,
    first_valid,
    eval_trial,
    node_to_cse,
    compute_build_root,
)
from husks.build.run import (
    _last_store,
    build,
)

# Re-export core.recipe_digest for callers that import it via husks.build
from husks.core import recipe_digest

__all__ = [
    "Store", "Node", "Recipe", "OracleBackend", "Stop",
    "site_path", "ensure_dir", "read_text", "write_text", "file_exists",
    "fresh_store", "burn", "file_sig",
    "_fn_behavior_digest", "_pred_identity", "VERDICT_POLICIES",
    "recipe_to_cse", "_ACTION_ARG_TYPES",
    "compute_cse_seal", "seal_file", "read_seal", "output_hashes",
    "freshness_check", "write_seal", "history_file", "append_history",
    "write_trial_report", "write_build_manifest", "_collect_rules",
    "rule", "action", "_make_shell_action", "oracle", "trial",
    "cond", "commit", "halt",
    "_check_declared_outputs", "eval_node", "eval_cond", "eval_rule",
    "eval_recipe", "default_oracle_backend", "eval_oracle",
    "first_valid", "eval_trial", "node_to_cse", "compute_build_root",
    "_last_store", "build",
]
