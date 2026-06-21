"""
router.py — Stage 1 (navigate) + render decision

Given a user query and the index.json graph, decide WHICH nodes to load
before answering. This is the cheap/fast tier (Haiku in production): it never
sees the full 48 pages, only the compact index.

Pipeline:
  1. score nodes against the query (entry-point selection)
  2. graph traversal: expand entry nodes 1 hop along typed edges
  3. underspecification check -> maybe ask a clarifying question instead
  4. render decision: for the winning nodes, pick the output modality
       (surface manual image | generate interactive artifact | text)

The deterministic scorer below is the OFFLINE fallback so the demo runs with
no API key. route_with_llm() shows where the Haiku call slots in — same
contract (query + index -> node ids), better recall on paraphrases.
"""

import json, re
from pathlib import Path

IDX = json.loads(Path("index.json").read_text())
NODES = {n["id"]: n for n in IDX["nodes"]}
EDGES = IDX["edges"]

# adjacency (undirected for traversal, but we keep the relation label)
ADJ = {}
for e in EDGES:
    ADJ.setdefault(e["src"], []).append((e["dst"], e["rel"]))
    ADJ.setdefault(e["dst"], []).append((e["src"], e["rel"]))

# which modalities should be RENDERED, not described
SURFACE_IMAGE = {"diagram", "photo", "schematic"}
BUILD_ARTIFACT = {            # node_id -> kind of interactive artifact to generate
    "duty_cycle_table":     "duty-cycle calculator",
    "penetration_control":  "settings configurator (process+material+thickness -> wire speed & voltage)",
    "troubleshooting":      "troubleshooting flowchart",
}

# queries that are ambiguous without a parameter -> clarify first
NEEDS_PARAMS = {
    "duty_cycle_table": ["process (MIG/TIG/Stick)", "amperage", "input voltage (120V/240V)"],
}


QSTOP = set("the a an of to and or for with on in is be are this that your you it "
            "do not what which does i'm im need get getting should my me at as".split())

def tokenize(s, drop_stop=False):
    toks = set(re.findall(r"[a-z0-9][a-z0-9\-]{2,}", s.lower()))
    return toks - QSTOP if drop_stop else toks


def score(query):
    q = tokenize(query, drop_stop=True)
    out = []
    for n in IDX["nodes"]:
        kws = set(n.get("keywords", [])) | set(n.get("auto_keywords", []))
        # expand multiword keywords into tokens too
        kw_tokens = set()
        for k in kws:
            kw_tokens |= tokenize(k)
        hits = q & kw_tokens
        # answerable-question overlap is a strong signal
        ans_tokens = set()
        for a in n.get("answers", []):
            ans_tokens |= tokenize(a)
        ans_hits = q & ans_tokens
        s = 2 * len(hits) + 3 * len(ans_hits)
        # assets beat their parent section on ties (more specific)
        if n["type"] == "asset":
            s += 0.5 if s > 0 else 0
        if s > 0:
            out.append((s, n["id"], sorted(hits | ans_hits)))
    return sorted(out, reverse=True)


def route(query, top_k=3, hops=1, rel_thresh=0.6):
    ranked = score(query)
    if not ranked:
        return {"query": query, "clarify": "No match in index — rephrase or escalate to full-text search.", "nodes": []}

    # keep entries close to the best score (a dominant match enters alone)
    best = ranked[0][0]
    entry = [nid for s, nid, _ in ranked[:top_k] if s >= rel_thresh * best]

    # underspecification check on the top entry node
    top = entry[0]
    if top in NEEDS_PARAMS:
        missing = [p for p in NEEDS_PARAMS[top] if not _mentions(query, p)]
        if missing:
            return {
                "query": query,
                "entry": entry,
                "clarify": f"'{NODES[top]['title']}' needs: {', '.join(missing)}. Ask the user before answering.",
                "nodes": entry,
            }

    # graph traversal: expand neighbors along SEMANTIC edges only
    # (skip contains/part_of which just pull whole section families)
    TRAVERSE = {"cause_of", "related", "prerequisite", "same_process"}
    selected = list(entry)
    frontier = list(entry)
    for _ in range(hops):
        nxt = []
        for nid in frontier:
            nbrs = [(nb, rel) for nb, rel in ADJ.get(nid, []) if rel in TRAVERSE]
            for nb, rel in nbrs[:4]:            # cap fan-out
                if nb not in selected:
                    selected.append(nb)
                    nxt.append(nb)
        frontier = nxt

    # render decision per selected node
    plan = []
    for nid in selected:
        n = NODES[nid]
        if nid in BUILD_ARTIFACT:
            action = f"GENERATE artifact: {BUILD_ARTIFACT[nid]}"
        elif n["modality"] in SURFACE_IMAGE:
            action = f"SURFACE image (rasterize p{n['pages'][0]} crop)"
        else:
            action = "TEXT (grounded from page text)"
        plan.append({
            "id": nid, "title": n["title"], "page": n["pages"][0],
            "modality": n["modality"], "via": "entry" if nid in entry else "graph-hop",
            "render": action,
        })
    return {"query": query, "entry": entry, "matched": ranked[0][2], "nodes": selected, "plan": plan}


def _mentions(query, param):
    # crude param presence check for the demo
    keys = {
        "process (MIG/TIG/Stick)": ["mig", "tig", "stick", "flux"],
        "amperage": [r"\d+\s*a", "amp"],
        "input voltage (120V/240V)": ["120", "240", "volt"],
    }
    ql = query.lower()
    return any(re.search(k, ql) for k in keys.get(param, []))


def route_with_llm(query):
    """Production tier-1 (sketch). Same contract, better paraphrase recall."""
    raise NotImplementedError("""
    from anthropic import Anthropic
    client = Anthropic()
    compact = [{k: n[k] for k in ('id','title','modality','pages','summary')} for n in IDX['nodes']]
    msg = client.messages.create(
        model="claude-haiku-4-5",            # cheap/fast routing tier
        max_tokens=300,
        system="You are a router. Given an index of manual nodes and a user "
               "question, return ONLY a JSON list of node ids most relevant. "
               "Prefer specific asset nodes over sections.",
        messages=[{"role":"user","content": json.dumps({'index':compact,'query':query})}],
    )
    return json.loads(msg.content[0].text)
    """)


SAMPLES = [
    "What's the duty cycle for MIG welding at 200A on 240V?",
    "I'm getting porosity in my flux-cored welds. What should I check?",
    "What polarity setup do I need for TIG welding? Which socket does the ground clamp go in?",
    "What's the duty cycle?",  # deliberately underspecified -> should clarify
]

if __name__ == "__main__":
    for q in SAMPLES:
        r = route(q)
        print("\n" + "=" * 78)
        print("Q:", q)
        if r.get("clarify"):
            print("  ↳ CLARIFY:", r["clarify"])
            if not r.get("plan"):
                continue
        print("  entry:", r.get("entry"), "| matched on:", r.get("matched"))
        for p in r.get("plan", []):
            tag = "•" if p["via"] == "entry" else "↳"
            print(f"   {tag} [{p['modality']:9}] p{p['page']:<2} {p['title']}")
            print(f"       → {p['render']}")
