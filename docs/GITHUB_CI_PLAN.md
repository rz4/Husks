# GitHub CI plan

Replaces the current `core-tests` and `beta-acceptance` jobs. Depends on the marker
redefinition in `TEST_TIERING.md` (alpha = solid invariants, beta = live evidence).

Three jobs:

- **Wheel Smoke** — keyless, matrix, required. Unchanged in spirit from today.
- **Solid Alpha** — keyless, matrix, required, the merge gate. Includes stub three-machine resolution.
- **Liquid Beta** — keyed, single Python, dispatch-only, non-blocking. One API call per trial.

## `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
    inputs:
      trials:
        description: "Liquid Beta: number of live three-machine trials to run"
        required: false
        default: "1"

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  wheel-smoke:
    name: Wheel Smoke
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
          cache: pip
      - run: |
          python -m pip install --upgrade pip build
          python -m build --wheel
          pip install dist/*.whl pytest
      - run: python -m pytest tests/test_wheel_smoke.py -v --tb=short

  solid-alpha:
    name: Solid Alpha
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.10", "3.11", "3.12", "3.13"]
    env:
      HUSKS_ENABLE_LIVE_TESTS: ""   # ensure no live path can be entered
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
          cache: pip
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e . pytest      # match the project's existing dev install
      - name: Stub three-machine resolution (headline invariant)
        run: |
          python -m pytest -m alpha \
            tests/test_three_machine_proof.py \
            tests/test_three_machine_cli_acceptance.py \
            tests/test_beta_three_machine.py \
            -v --tb=short
      - name: Full deterministic suite
        run: |
          python -m pytest tests/ -m "not beta" \
            --ignore=tests/test_live_oracle_readiness.py \
            -v --tb=short

  liquid-beta:
    name: Liquid Beta (live three-machine)
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    environment: live-oracle   # optional: scopes the secret, can require manual approval
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install (with live oracle extra)
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[llm]" pytest   # install whatever extra pulls litellm/anthropic
      - name: Live three-machine demo
        continue-on-error: true
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          HUSKS_ENABLE_LIVE_TESTS: "1"
          HUSKS_LIVE_TRIALS: ${{ github.event.inputs.trials }}
        run: |
          python -m pytest -m beta tests/test_live_oracle_readiness.py \
            -v --tb=short
```

## Wiring notes

- **Branch protection**: mark every `Wheel Smoke` and `Solid Alpha` matrix entry as a required status check. Do **not** require `Liquid Beta`. The red/green badge then reflects deterministic invariants only.
- **Triggers**: Liquid Beta runs only on `workflow_dispatch`. It never runs on push, PR, or schedule, so it costs an API call only when you click run.
- **Fork safety**: `workflow_dispatch` can be triggered only by users with write access, and fork PRs cannot read secrets. Together these keep the key off untrusted code with no extra guard. The optional `environment: live-oracle` adds a manual-approval gate and scopes the secret to this job if you want belt-and-suspenders.
- **`continue-on-error: true`** on the live step: a single live divergence records as a failed step but does not fail the job or turn the repo red. The trial outcome is the output, not a gate.
- **`HUSKS_ENABLE_LIVE_TESTS: ""`** is set explicitly on Solid Alpha so a stray live test can never execute there even if mismarked. `test_version_terminology.py` enforces that no live test carries `alpha` and no stub-only test carries `beta`.
- **`trials` input** is plumbed to `HUSKS_LIVE_TRIALS` now so the dispatch UI already takes a count. Until Part D, the live test can ignore it or loop trivially; Part D makes it run k stratified trials plus the negative and positive controls and append k sealed records to the evidence ledger.

## Assumptions to confirm before merging

- The install extras (`pip install -e .` for alpha, `".[llm]"` for beta) match the project's actual packaging. Reuse whatever the current `ci.yml` install step does rather than these guesses.
- The three stub three-machine files named in the headline step are the right set after any rename from `TEST_TIERING.md` (e.g. `test_beta_three_machine.py` → `test_three_machine_stub.py`). Keep the step's file list in sync with the rename.
- `ANTHROPIC_API_KEY` exists as a repo (or `live-oracle` environment) secret.

## Order of operations

1. Land the marker redefinition and reassignment from `TEST_TIERING.md`.
2. Land this `ci.yml`.
3. Set branch protection to require Wheel Smoke and Solid Alpha.
4. Confirm a manual `Run workflow` dispatch executes Liquid Beta and a normal PR shows only the two required jobs.
