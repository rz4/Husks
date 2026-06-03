# Husks Documentation

> **Build Husks, not vibes.** This index is a reading **DAG**, not a flat list.

There are two ways through these docs.

**Top-down, by need.** Start at the surface and stop when your question is
answered. Most people never need to go below the first stratum.

**Deep, by register.** Read the whole descent. The further down you go, the
more the register shifts — from *how you use it*, to the *philosophy* it rests
on, to the *science* that makes it trustworthy, to the *formal math* that
defines what it actually is. Each stratum is a prerequisite for the one below
it, never the reverse.

The descent mirrors the codebase's own layer structure in reverse: you enter at
the **L7** user surface (`cli`) and descend toward the **L0** kernel (`core`),
where the wire format and the seal algebra live. The code's dependency arrows
point *down* toward the kernel; a reader's attention travels the same spine in
the same direction. (The machine-checkable version of that spine is
[`../layers.toml`](../layers.toml); see [the DAG rationale](husks-dag-rearchitecture.md).)

---

## The reading DAG

```mermaid
flowchart TD
    classDef surface fill:#e8f0fe,stroke:#3b6fd4,color:#10243e;
    classDef philos  fill:#f3e8fe,stroke:#8b46c9,color:#2a0f3e;
    classDef science fill:#e8fbef,stroke:#2faa5d,color:#0f3320;
    classDef formal  fill:#fdeede,stroke:#d4863b,color:#3e2410;
    classDef meta    fill:#f1f1f1,stroke:#999,color:#333,stroke-dasharray:4 3;

    FRONT["README — front door<br/><i>what Husks is, install, the proof</i>"]:::surface
    TUT["tutorial.md — mental model<br/><i>Author / Producer / Verifier roles</i>"]:::surface
    CLI["liquid-beta.md — CLI reference<br/><i>commands, schema, FAQ</i>"]:::surface
    LOCKE["locke.md — the Locke language<br/><i>surface syntax → CSE</i>"]:::surface

    STANCE["theory.md — the residue stance<br/><i>why an opaque event, not an agent loop</i>"]:::philos
    WP["white_paper.pdf — the argument<br/><i>the synthesized case</i>"]:::philos

    PROOF["three-machine-proof.md — the proof<br/><i>independent re-realization, gates A–H</i>"]:::science
    CONF["spec/conformance — two readers<br/><i>one language, provably</i>"]:::science

    CSE["spec/CSE-v2.md — wire format<br/><i>the canonical bytes</i>"]:::formal
    SEAL["architecture.md — the calculus<br/><i>seal preimage · Merkle digest · identity</i>"]:::formal
    DAG["husks-dag-rearchitecture.md — codebase as DAG<br/><i>layers, invariants, the contract</i>"]:::formal

    META["ROADMAP · EXPLORE · TESTS · phase-*-complete<br/><i>contributor / process / history</i>"]:::meta

    FRONT --> TUT --> CLI --> LOCKE
    FRONT -. "why this way" .-> STANCE
    TUT  -. "why this way" .-> STANCE
    STANCE --> WP
    STANCE --> PROOF
    LOCKE --> PROOF
    PROOF --> CONF
    PROOF --> CSE
    CONF  --> CSE
    LOCKE --> CSE
    CSE --> SEAL
    SEAL --> DAG
    DAG -. "implements" .-> META
```

Solid arrows are *read-before* prerequisites. Dashed arrows are *go-deeper*
pointers you can defer. The four colors are the four registers, top to bottom:
**surface → philosophy → science → formal**.

---

## Stratum 1 — Surface · *use it* · architecture L7 (`cli`), L5 (`design.locke`)

The public face. Friendly, task-oriented, no theory required.

| Document | Answers | Read after |
| :-- | :-- | :-- |
| [`../README.md`](../README.md) | What is Husks? How do I install it and run the proof? | — |
| [tutorial.md](tutorial.md) | How do I drive it from Claude Code? What are the three roles? | README |
| [liquid-beta.md](liquid-beta.md) | What does each command do? What's the JSON/Locke schema? | tutorial |
| [locke.md](locke.md) | What is the Locke design language and why does it look like that? | liquid-beta |

If all you want is to build something, you can stop here.

## Stratum 2 — Philosophy · *why it's built this way* · the posture beneath every layer

Husks rests on one methodological choice: treat a model call as an opaque
event and verify only its **residue** — the bytes left on disk. This stratum is
the *why*. It is upstream of everything technical.

| Document | Answers | Read after |
| :-- | :-- | :-- |
| [theory.md](theory.md) | Why verify residue instead of grading the event? Why not an agent loop? | the surface (or read first, if you came for the idea) |
| [white_paper.pdf](white_paper.pdf) | The full synthesized argument. | theory.md |

## Stratum 3 — Science · *why you can trust it* · architecture L3 (`build`), L0 gate

A claim is only worth as much as its falsifiability. This stratum is the
empirical core: the same design, realized independently, must produce
verifiably equivalent residue — and two independent readers must accept exactly
the same language.

| Document | Answers | Read after |
| :-- | :-- | :-- |
| [three-machine-proof.md](three-machine-proof.md) | What exactly must hold for "beta"? What do gates A–H verify? | theory.md |
| [spec/conformance/](../spec/conformance/) | How do we prove the Python reader and the JS reader agree? | three-machine-proof |

## Stratum 4 — Formal / Math · *what it actually is* · architecture L1–L0 (`core`)

The bottom. Here the system is defined, not described: a canonical byte
encoding, a seal preimage, a Merkle node digest, and the recipe-identity
algebra that makes two builds provably the same.

| Document | Answers | Read after |
| :-- | :-- | :-- |
| [spec/CSE-v2.md](../spec/CSE-v2.md) | What are the canonical bytes? (Current wire version.) | the science stratum |
| [spec/CSE-v1.md](../spec/CSE-v1.md) | The frozen prior wire version, kept for vector stability. | CSE-v2 |
| [architecture.md](architecture.md) | Seal preimage, node digest (Merkle DAG), recipe identity, the execution calculus. | CSE-v2 |
| [husks-dag-rearchitecture.md](husks-dag-rearchitecture.md) | Why the *codebase* is itself a sealed DAG; the layer invariants. | architecture.md |
| [`../layers.toml`](../layers.toml) | The machine-checkable layer contract (`husks doctor --arch`). | husks-dag-rearchitecture |

## Off the spine — Contributor / process

Not part of the conceptual descent; consult as needed.

| Document | Contents |
| :-- | :-- |
| [ROADMAP.md](ROADMAP.md) | Hardening workstreams (permanence, CLI, transport), ordered by leverage. |
| [EXPLORE.md](EXPLORE.md) | Exploration backlog, ranked by compound value. |
| [TESTS.md](TESTS.md) | Test-suite map: CSE GENESIS / SOLID ALPHA / LIQUID BETA phases and naming. |
| [phase-0-complete.md](phase-0-complete.md) · [phase-1-complete.md](phase-1-complete.md) · [phase-2-complete.md](phase-2-complete.md) | Rearchitecture phase records (what each cycle-cut accomplished). |

---

### Maintainer note

The descent is only honest if each node stays at its own register and points
*down*, never sideways into a peer's job. Two known drifts to reconcile:

- **`architecture.md`'s module map** (top section) still describes the
  pre-rearchitecture layout (`designs/` with `ir.py`, single `cli.py`/`build.py`,
  no `design/locke/`). Its formal sections (wire format, seal, node digest) are
  accurate and carry this stratum; the map needs updating to the L0–L7 package
  tree before it can be cited as the architecture source of truth.
- **The root `README.md`'s "Run the Tests Locally"** still names
  `tests/test_three_machine_proof.py` etc.; those files are now
  `tests/test_LIQUID_69_three_machine_proof.py` and siblings. The headline
  commands also still pass `core-bootstrap.json`, while the shipped examples are
  `core-bootstrap.locke`.
