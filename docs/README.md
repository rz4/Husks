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
the **L7** user surface (`cli`) and descend toward the **L0** kernel, where the
wire format and the seal algebra live. The code's dependency arrows point *down*
toward the kernel; a reader's attention travels the same spine in the same
direction. (The machine-checkable version of that spine is
[`../layers.toml`](../layers.toml).)

---

## The reading DAG

```mermaid
flowchart TD
    classDef surface fill:#e8f0fe,stroke:#3b6fd4,color:#10243e;
    classDef philos  fill:#f3e8fe,stroke:#8b46c9,color:#2a0f3e;
    classDef science fill:#e8fbef,stroke:#2faa5d,color:#0f3320;
    classDef formal  fill:#fdeede,stroke:#d4863b,color:#3e2410;

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
```

Solid arrows are *read-before* prerequisites. Dashed arrows are *go-deeper*
pointers you can defer. The four colors are the four registers, top to bottom:
**surface → philosophy → science → formal**.

---

## Stratum 1 — Surface · *use it* · L7 (`cli`), L5 (`locke`)

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

## Stratum 3 — Science · *why you can trust it* · L3 (`engine`), L0 gate

A claim is only worth as much as its falsifiability. This stratum is the
empirical core: the same design, realized independently, must produce
verifiably equivalent residue — and two independent readers must accept exactly
the same language.

| Document | Answers | Read after |
| :-- | :-- | :-- |
| [three-machine-proof.md](three-machine-proof.md) | What exactly must hold for "beta"? What do gates A–H verify? | theory.md |
| [spec/conformance/](../spec/conformance/) | How do we prove the Python reader and the JS reader agree? | three-machine-proof |

## Stratum 4 — Formal / Math · *what it actually is* · L1–L0 (`kernel`)

The bottom. Here the system is defined, not described: a canonical byte
encoding, a seal preimage, a Merkle node digest, and the recipe-identity
algebra that makes two builds provably the same.

| Document | Answers | Read after |
| :-- | :-- | :-- |
| [spec/CSE-v2.md](../spec/CSE-v2.md) | What are the canonical bytes? (Current wire version.) | the science stratum |
| [spec/CSE-v1.md](../spec/CSE-v1.md) | The frozen prior wire version, kept for vector stability. | CSE-v2 |
| [architecture.md](architecture.md) | Seal preimage, node digest (Merkle DAG), recipe identity, the execution calculus. | CSE-v2 |
| [`../layers.toml`](../layers.toml) | The machine-checkable layer contract (`husks doctor --arch`). | architecture.md |

## Off the spine — Contributor / process

Not part of the conceptual descent; consult as needed.

| Document | Contents |
| :-- | :-- |
| [BACKLOG.md](BACKLOG.md) | Consolidated backlog: unchecked hardening items + exploration items, ordered by leverage. |
| [TESTS.md](TESTS.md) | Test-suite map: CSE GENESIS / SOLID ALPHA / LIQUID BETA phases and naming. |
