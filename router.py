"""
router.py — Stage 1 (route) + render decision   [STRUCTURE DEMO]

This is a demo of the *architecture*, not a retrieval engine. Stage 1 splits
cleanly into two parts by who owns them:

  • ENTRY-POINT SELECTION  — "which node(s) answer this question?"
    This is the MODEL's job. In production a cheap tier (Haiku, or an embedding
    lookup) reads the compact index and returns node ids. There is deliberately
    NO keyword scorer here pretending to be smart — instead each scenario
    DECLARES the entry nodes the router would return, so the demo is honest and
    deterministic. route_with_llm() shows the real call (same contract).

  • TRAVERSAL + RENDER DECISION  — given the entry nodes, everything downstream
    is pure structure, and THIS is real code:
      - bounded 1-hop traversal along a TYPED, DIRECTED relation policy
      - underspecification check (missing params -> clarify, don't answer)
      - per-node render decision (surface image | generate artifact | text)

The point of the demo is to show the graph machinery, not to score text.
"""

import json
from pathlib import Path

IDX = json.loads(Path("index.json").read_text())
NODES = {n["id"]: n for n in IDX["nodes"]}

# --- Relation policy -------------------------------------------------------
# Edges are typed AND directed; traversal respects direction (this is the
# whole reason cross-referencing works without dragging in noise).
#
#   cause_of / prerequisite  -> followed FORWARD only. Direction is meaningful:
#       a DEFECT points to its root CAUSES; a TASK points to its PREREQUISITES.
#       Walking them backward (from a cause to every defect it could produce)
#       is noise, so we don't.
#   same_process             -> symmetric (MIG nodes cluster with MIG nodes).
# These three PULL content into the load set.
#
#   related                  -> soft. Surfaced as "see also", never auto-loaded.
#   contains / part_of       -> structural. Never traversed for loading.
LOAD_DIRECTED  = {"cause_of", "prerequisite"}
LOAD_SYMMETRIC = {"same_process"}
SEE_ALSO       = {"related"}

OUT, SOFT = {}, {}
for e in IDX["edges"]:
    s, d, r = e["src"], e["dst"], e["rel"]
    if r in LOAD_DIRECTED:
        OUT.setdefault(s, []).append((d, r))
    elif r in LOAD_SYMMETRIC:
        OUT.setdefault(s, []).append((d, r))
        OUT.setdefault(d, []).append((s, r))
    elif r in SEE_ALSO:
        SOFT.setdefault(s, []).append(d)
        SOFT.setdefault(d, []).append(s)

# --- Render policy ---------------------------------------------------------
# This is what makes the output multimodal: the decision is keyed off node
# modality, decided here at route time (not left to the answer model's whim).
SURFACE_IMAGE = {"diagram", "photo", "schematic"}
BUILD_ARTIFACT = {            # node_id -> kind of interactive artifact to generate
    "duty_cycle_table":    "duty-cycle calculator",
    "penetration_control": "settings configurator (process+material+thickness -> wire speed & voltage)",
    "troubleshooting":     "troubleshooting flowchart",
}

# Nodes whose answer is meaningless without parameters -> clarify before answering.
NEEDS_PARAMS = {
    "duty_cycle_table": ["process (MIG/TIG/Stick)", "amperage", "input voltage (120V/240V)"],
}

# --- Scenarios -------------------------------------------------------------
# Each entry is what the routing TIER (Haiku / embeddings) would return for a
# question: the entry node id(s) it selects + the structured params it extracted.
# We declare these instead of scoring text — see module docstring.
SCENARIOS = [
    {"q": "What's the duty cycle for MIG welding at 200A on 240V?",
     "entry": ["duty_cycle_table"],
     "params": ["process (MIG/TIG/Stick)", "amperage", "input voltage (120V/240V)"],
     "note": "fully specified -> direct table lookup, no hop needed"},
    {"q": "I'm getting porosity in my flux-cored welds. What should I check?",
     "entry": ["weld_diagnosis"], "params": [],
     "note": "defect node -> cause_of edges pull the candidate root causes"},
    {"q": "What polarity setup do I need for TIG welding? Which socket does the ground clamp go in?",
     "entry": ["tig_polarity"], "params": [],
     "note": "direct diagram surface; cause_of is incoming, so nothing extra is pulled"},
    {"q": "What's the duty cycle?",
     "entry": ["duty_cycle_table"], "params": [],
     "note": "underspecified -> clarify before answering"},
]


def render_row(nid, via):
    n = NODES[nid]
    if nid in BUILD_ARTIFACT:
        action = f"GENERATE artifact: {BUILD_ARTIFACT[nid]}"
    elif n["modality"] in SURFACE_IMAGE:
        action = f"SURFACE image (rasterize p{n['pages'][0]})"
    else:
        action = "TEXT (grounded from page text)"
    return {"id": nid, "title": n["title"], "page": n["pages"][0],
            "modality": n["modality"], "via": via, "render": action}


def route(entry, params_present, query=None, max_fanout=4):
    """Given the entry node(s) the router selected, traverse + decide render."""
    top = entry[0]

    # 1. underspecification check on the entry node
    if top in NEEDS_PARAMS:
        missing = [p for p in NEEDS_PARAMS[top] if p not in params_present]
        if missing:
            return {"query": query, "entry": entry,
                    "clarify": f"'{NODES[top]['title']}' needs: {', '.join(missing)}. "
                               f"Ask the user before answering.",
                    "loaded": [], "see_also": [], "plan": []}

    # 2. 1-hop directed traversal along the typed load-edges
    via = {nid: "entry" for nid in entry}
    loaded = list(entry)
    for nid in entry:
        for nb, rel in OUT.get(nid, [])[:max_fanout]:
            if nb not in via:
                via[nb] = rel
                loaded.append(nb)

    # 3. soft "see also" suggestions (related edges — surfaced, not loaded)
    see_also = []
    for nid in loaded:
        for nb in SOFT.get(nid, []):
            if nb not in via and nb not in see_also:
                see_also.append(nb)

    # 4. render decision per loaded node
    plan = [render_row(nid, via[nid]) for nid in loaded]
    return {"query": query, "entry": entry, "loaded": loaded,
            "see_also": see_also, "plan": plan}


def route_with_llm(query):
    """Production entry-point selection (sketch). Same contract: query -> node ids."""
    raise NotImplementedError("""
    from anthropic import Anthropic
    client = Anthropic()
    # hand the cheap tier ONLY the compact index (~2k tokens), never full pages
    compact = [{k: n[k] for k in ('id','title','modality','pages','summary')} for n in IDX['nodes']]
    msg = client.messages.create(
        model="claude-haiku-4-5",            # cheap/fast routing tier
        max_tokens=300,
        system="You are a router. Given an index of manual nodes and a user "
               "question, return ONLY JSON: {\\"entry\\": [node ids], \\"params\\": [...]}. "
               "Prefer specific asset nodes over sections.",
        messages=[{"role":"user","content": json.dumps({'index':compact,'query':query})}],
    )
    sel = json.loads(msg.content[0].text)
    return route(sel['entry'], sel.get('params', []), query)   # same downstream path
    """)


if __name__ == "__main__":
    for sc in SCENARIOS:
        r = route(sc["entry"], sc["params"], sc["q"])
        print("\n" + "=" * 78)
        print("Q:", sc["q"])
        print("  ·", sc["note"])
        print("  router selects entry:", r["entry"], "(declared — Haiku's job in prod)")
        if r.get("clarify"):
            print("  ↳ CLARIFY:", r["clarify"])
            continue
        for p in r["plan"]:
            tag = "•" if p["via"] == "entry" else f"↳ {p['via']}"
            print(f"   {tag:14} [{p['modality']:9}] p{p['page']:<2} {p['title']}")
            print(f"       → {p['render']}")
        if r["see_also"]:
            sa = ", ".join(NODES[i]["title"] for i in r["see_also"])
            print(f"   see also (related, not loaded): {sa}")
