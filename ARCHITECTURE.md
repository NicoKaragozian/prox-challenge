# OmniPro 220 Agent — Architecture / Problem Decomposition

A multimodal reasoning agent over the Vulcan OmniPro 220 owner's manual
(48 pp). This doc is the **decomposition + a runnable demo of the retrieval
structure** — not the finished product.

## The problem, restated

Three hard parts, in order of weight:

1. **Knowledge extraction** — the manual is text **+** tables **+** labeled
   diagrams **+** photos **+** an electrical schematic. Critical answers exist
   *only as images* (weld-diagnosis photos p35/37–38, wiring schematic p45,
   polarity socket diagrams p11/p24). A text-only RAG silently drops these.
   Evidence: the schematic page's text layer extracts **mirrored**
   (`eriw`=wire, `evlav`=valve, `draob`=board) — it's a picture, not text.
2. **Routing without dumping 48 pages into context** — answer accuracy and
   cost both die if every query loads the whole manual. Need a cheap step that
   decides *what to load*.
3. **Multimodal output** — the agent must *show*: surface the manual image, or
   **generate an interactive artifact** (duty-cycle calculator, settings
   configurator, troubleshooting flowchart), not just describe.

## Pipeline

```
            ┌── Stage 0: INGEST (offline, build_index.py) ─────────────┐
            │  manual.pdf → typed knowledge graph (index.json)         │
            │  • detect structure: pages, table/image counts → modality│
            │  • semantic layer: summary + keywords + answerable Qs    │
            │    (LLM-generated at ingest in prod; curated+grounded here)│
            └──────────────────────────────────────────────────────────┘
 query ─► Stage 1: ROUTE  (cheap/fast tier — Haiku)        router.py
            • reads ONLY the index (~2k tokens), never full pages
            • score → pick entry node(s)
            • graph traversal: expand entry along SEMANTIC edges (cross-refs)
            • underspecified? → ask a clarifying question, stop
       ─► Stage 2: LOAD
            • pull full content of selected nodes: page text + rasterized
              diagrams/photos (vision) — and nothing else
       ─► Stage 3: ANSWER (smart tier — Opus/Sonnet)
            • grounded answer, cites node/page → low hallucination
       ─► Stage 4: RENDER decision (per node)
            • SURFACE  image  (diagram / photo / schematic)
            • GENERATE artifact (table/matrix → calculator/configurator/flowchart)
            • TEXT
```

Two model tiers is the core cost/latency/grounding move: the expensive model
only ever sees a handful of *relevant, verified* nodes.

## The graph

**Nodes** = manual sections (coarse) + asset nodes (fine: a specific table,
diagram, photo, schematic, matrix). 20 nodes / 28 edges here. Each node is
tagged with a **modality** — this is what makes the output multimodal: routing
returns *pointers to assets*, not just text spans.

**Edges** are typed:

| relation       | meaning                                   | used in traversal |
|----------------|-------------------------------------------|:-----------------:|
| `contains`     | section → its assets (hierarchy)          |  no (structural)  |
| `part_of`      | asset → section                           |  no               |
| `same_process` | MIG nodes ↔ MIG nodes, etc.               |  yes              |
| `prerequisite` | "set polarity before loading wire"        |  yes              |
| `related`      | soft cross-reference                      |  yes              |
| `cause_of`     | defect → root-cause node                  |  yes              |

The `cause_of` edges are why a cross-referencing question works. **"Porosity in
flux-cored welds?"** enters at the *weld-diagnosis photo* node and walks
`cause_of` to polarity + wire-feed-tension + penetration — exactly the
multi-section answer the challenge tests, assembled by graph traversal instead
of one fat similarity search.

Graph-theory hooks worth saying out loud in the interview: entry-point
selection = seeded retrieval; traversal = bounded BFS along a typed relation
whitelist; hub nodes (duty-cycle table, safety) have high degree and could be
ranked by centrality; `prerequisite` edges give a partial order for "setup"
questions.

## What the demo shows (and doesn't)

**Shows (real, on the actual manual):**
- `build_index.py` → parses the 48-page PDF into `index.json` (structure
  auto-detected, modality from real table/image counts).
- `router.py` → two-tier routing on the challenge's 3 sample questions +
  an underspecified one → prints entry node, graph hops, and the render plan.
- `graph_demo.html` → interactive: type a question, watch the entry node strike
  and current flow along the cross-reference edges; side panel shows the load
  plan with per-node render decisions.

**Stubbed (deliberately — this is a structure demo):**
- Stage 1 has a deterministic offline scorer so it runs with no key;
  `route_with_llm()` shows the Haiku call (same contract). Swap in for better
  paraphrase recall.
- Stage 2/3 (load pages + Opus answer) and Stage 4 artifact *generation* are
  specified, not built. The Claude Agent SDK wiring + frontend is the next step.

## Why this answers the brief

- **Extraction quality** → modality-typed nodes; image-only content is
  first-class, not lost.
- **Accuracy / no hallucination** → smart model is constrained to retrieved,
  cited nodes; cross-refs come from explicit edges, not vibes.
- **Multimodal** → the render decision is a real branch in the pipeline, keyed
  off node modality.
- **Ambiguity** → the clarify check fires before answering when params are
  missing (process / amperage / voltage).

## Run

```bash
pip install pdfplumber
python build_index.py     # → index.json  (reads challenge/files/owner-manual.pdf)
python router.py          # → routing trace on the sample questions
open graph_demo.html      # interactive (self-contained, graph inlined)
```
