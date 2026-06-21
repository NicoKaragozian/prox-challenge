# OmniPro 220 Agent — Architecture Demo

A multimodal reasoning agent over the Vulcan OmniPro 220 owner's manual (48 pp),
built for the [Prox Founding Engineer Challenge](challenge/README.md).

> **What this repo is.** This is a **runnable demo of the retrieval architecture**,
> not the finished agent. It exists to show *how* the system is decomposed and *why* —
> the typed knowledge graph, the two-tier router, and the multimodal render decision.
> The full Claude Agent SDK wiring, page loading, answer generation, and artifact
> generation are specified but deliberately stubbed. See **[ARCHITECTURE.md](ARCHITECTURE.md)**
> for the complete decomposition and the line between what's real and what's next.

## The core idea

A 48-page manual is text **+** tables **+** labeled diagrams **+** photos **+** an
electrical schematic. Critical answers exist *only as images* (weld-diagnosis photos,
wiring schematic, polarity socket diagrams). A text-only RAG silently drops these —
you can even see it: the schematic page's text layer extracts **mirrored**
(`eriw`=wire, `evlav`=valve), because it's a picture, not text.

So instead of one flat similarity search, the manual is parsed into a **typed
knowledge graph**:

- **Nodes** carry a `modality` (`text / table / diagram / photo / schematic / matrix`).
  This is what makes responses multimodal — routing returns *pointers to assets*, not just text spans.
- **Edges** are typed (`cause_of`, `prerequisite`, `related`, `same_process`, `contains`).
  Cross-referencing questions are answered by **graph traversal**, not vibes:
  *"porosity in flux-cored welds?"* enters at the weld-diagnosis photo node and walks
  `cause_of` edges to polarity + wire-feed-tension + penetration.

A **two-tier** flow keeps cost and grounding under control: a cheap/fast model (Haiku)
reads only the ~2k-token index to pick nodes; the expensive model (Opus) only ever sees
the handful of *relevant, verified* nodes that were loaded.

```
INGEST (build_index.py) → ROUTE/Haiku (router.py) → LOAD → ANSWER/Opus → RENDER decision
```

## What's in here

| File | Stage | Status |
|------|-------|--------|
| `build_index.py` | **0 · Ingest** — parse the PDF into a typed graph (`index.json`). Structure (pages, table/image counts → modality) is auto-detected; the semantic layer is curated + grounded here, LLM-generated at ingest in prod. | ✅ real |
| `index.json` | The built graph: 20 nodes, 28 edges. | ✅ real |
| `router.py` | **1 · Route** — score query → entry node → graph traversal → underspecification (clarify) check → per-node render decision. Deterministic offline scorer so it runs with **no API key**; `route_with_llm()` shows the Haiku call (same contract). | ✅ real |
| `graph_demo.html` | Interactive visualization — type a question, watch the entry node strike and current flow along the cross-reference edges; side panel shows the load plan with per-node render decisions. Self-contained (graph inlined). | ✅ real |
| **Stages 2–4** | Load pages + Opus answer + artifact *generation* (duty-cycle calculator, settings configurator, troubleshooting flowchart) and the Agent SDK + frontend wiring. | 🚧 specified, next |

## Run

No API key needed — the demo runs on a deterministic offline scorer.

```bash
# interactive visualization (self-contained, nothing to install)
open graph_demo.html

# routing trace on the challenge's 3 sample questions + 1 underspecified one
python router.py

# (optional) rebuild the graph from the PDF
pip install pdfplumber
python build_index.py        # reads challenge/files/owner-manual.pdf → index.json
```

`router.py` reproduces the challenge's three test questions plus a deliberately
underspecified one (*"What's the duty cycle?"* → asks for process/amperage/voltage
before answering).

## Repo layout

```
.
├── README.md            ← you are here (the solution)
├── ARCHITECTURE.md      ← full problem decomposition + design decisions
├── build_index.py       ← Stage 0: PDF → typed knowledge graph
├── index.json           ← the built graph (20 nodes, 28 edges)
├── router.py            ← Stage 1: two-tier router + render decision
├── graph_demo.html      ← interactive visualization of the router
└── challenge/           ← the original challenge brief + product manuals
    ├── README.md
    └── files/           ← owner-manual.pdf, quick-start-guide.pdf, selection-chart.pdf
```
