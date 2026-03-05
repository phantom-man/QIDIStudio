"""
agents/manufacturing_graph.py — Cyber-Physical Feedback Loop as LangGraph StateGraph.

Architecture (from "Neural-Symbolic Integration" design):
  LangGraph manages the Cognitive State (WHY to act)
  PyTorch (via torch_tools) is the Differentiable Execution Kernel (HOW physics works)
  LangSmith is the Proprioceptive Feedback Loop (WHAT happened and WHAT to learn)

Graph Flow:
  START
    └─ stress_analysis   (PyTorch GNN — is the part safe to print?)
         └─ route_by_stress ──┬── "redesign" → redesign_node → END
                              └── "texture"  → texture_node
                                    └─ quality_gate ──┬── "pass"   → export_node → END
                                                      └─ "iterate" → texture_node (up to 3×)
                                                            └─ "timeout" → export_node → END

State schema (ManufacturingState) holds BOTH:
  Symbolic data  — messages, verdicts, recommendations (LLM-readable)
  Sub-symbolic   — stress_tensors, failure_probability, uv_stats, torch_metadata

LangSmith integration:
  Every node run is a child span under a parent "manufacturing-run" trace.
  Tensor metadata (latency, GPU delta, model version) attached to each span.
  Hardware feedback loop: print outcomes posted back to the originating trace.

Usage:
    from agents.manufacturing_graph import run_manufacturing_pipeline
    result = run_manufacturing_pipeline(
        stl_path="path/to/part.stl",
        part_name="vacuum_nozzle_lower",
        query="Apply grippy texture, ensure structural integrity for ABS at 270°C",
    )
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langsmith import traceable
from typing_extensions import NotRequired, TypedDict

# ── Env ───────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_PROJECT", "qidistudio-manufacturing")

# ── LanceDB memory ────────────────────────────────────────────────────────────
try:
    from memory.store import upsert_learning

    _LANCEDB_OK = True
except Exception:
    _LANCEDB_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# I.  State Schema  — Symbolic + Sub-symbolic (PhD pattern)
# ═══════════════════════════════════════════════════════════════════════════════


def _add_messages(left: list, right: list) -> list:
    return left + right


class ManufacturingState(TypedDict):
    """Shared state across all graph nodes.

    Symbolic fields  (LLM-readable text & verdicts)
    Sub-symbolic fields  (tensors, UV stats, float scores)
    """

    # ── Request context ───────────────────────────────────────────────────────
    stl_path: str
    part_name: str
    query: str
    thread_id: str

    # ── LangSmith anchor ─────────────────────────────────────────────────────
    langsmith_run_id: NotRequired[str]

    # ── Symbolic / reasoning ─────────────────────────────────────────────────
    messages: Annotated[list, _add_messages]
    current_route: NotRequired[str]  # "texture" | "redesign" | "done"
    redesign_suggestion: NotRequired[str]
    texture_verdict: NotRequired[str]  # "PASS" | "FAIL" | "PENDING"
    texture_iteration: NotRequired[int]
    export_path: NotRequired[str]

    # ── Sub-symbolic / physics ────────────────────────────────────────────────
    failure_probability: NotRequired[float]  # from PyTorch GNN
    high_stress_vertex_pct: NotRequired[float]
    hotspot_centroid: NotRequired[list[float]]
    risk_label: NotRequired[str]  # "SAFE" | "WARNING" | "CRITICAL"
    torch_metadata: NotRequired[dict]  # latency, GPU delta, backend

    # ── Texture scores (from last assess_quality / inspect_and_assess) ───────
    uniformity_score: NotRequired[float]
    seam_score: NotRequired[float]
    beauty_score: NotRequired[float]

    # ── Hardware outcome (set by hardware_feedback.py post-print) ─────────────
    print_outcome: NotRequired[str]  # "SUCCESS" | "FAIL" | "PENDING"
    print_outcome_notes: NotRequired[str]


# ═══════════════════════════════════════════════════════════════════════════════
# II.  LLM Factory
# ═══════════════════════════════════════════════════════════════════════════════

_GCP_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "crafty-hook-483415-b3")
_GCP_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")


def _llm(pro: bool = False) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-pro" if pro else "gemini-2.5-flash",
        temperature=0.0,
        project=_GCP_PROJECT,
        location=_GCP_LOCATION,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# III.  Graph Nodes
# ═══════════════════════════════════════════════════════════════════════════════


def stress_analysis_node(state: ManufacturingState) -> dict:
    """
    PyTorch Execution Node — "The Motor Cortex"

    Loads the STL, extracts vertices + normals, runs MeshStressPointNet
    (a PointNet-style per-vertex regressor, not a graph network — see
    agents/torch_tools.py for architecture notes), then writes sub-symbolic
    tensor results + a semantic recommendation into state.
    The LLM in reasoning_node reads the recommendation string, not raw tensors.

    Weight status: the PointNet ships with *randomly initialised* weights until
    a supervised training run on FEA-derived stress labels is complete
    (Phase 4.3).  Until then, failure_probability and risk_label values are
    statistically meaningless — routing decisions are effectively random and
    should NOT be used to block production prints.
    """
    from agents.torch_tools import evaluate_mesh_structural_integrity

    stl_path = state["stl_path"]

    # Extract vertex data from STL
    vertices, normals = _load_stl_vertices(stl_path)

    # Run PyTorch inference (or heuristic fallback)
    result = evaluate_mesh_structural_integrity.invoke(
        {
            "vertices": vertices,
            "normals": normals,
            "material_pla_hs": True,
        }
    )

    system_msg = SystemMessage(
        content=(
            "You are a structural integrity analyst for FFF 3D printing. "
            "Interpret the stress analysis result and decide: ROUTE_TO_TEXTURE or ROUTE_TO_REDESIGN. "
            "Reply with exactly one of those two strings on the first line, then your reasoning."
        )
    )
    human_msg = HumanMessage(
        content=(
            f"Part: {state['part_name']}\n"
            f"Query: {state['query']}\n"
            f"Stress analysis result:\n{json.dumps(result, indent=2)}"
        )
    )

    llm_response = _llm().invoke([system_msg, human_msg])
    response_text = llm_response.content.strip()
    first_line = response_text.splitlines()[0].strip()
    route = "redesign" if "REDESIGN" in first_line.upper() else "texture"

    _lancedb_log(
        topic=f"stress analysis: {state['part_name']}",
        decision=f"Risk={result['risk_label']} fp={result['failure_probability']} route={route}",
        content=json.dumps(result),
        category="workflow",
    )

    return {
        "failure_probability": result["failure_probability"],
        "high_stress_vertex_pct": result["high_stress_vertex_pct"],
        "hotspot_centroid": result["hotspot_centroid"],
        "risk_label": result["risk_label"],
        "torch_metadata": result["torch_metadata"],
        "current_route": route,
        "messages": [
            HumanMessage(
                content=f"Stress analysis complete. Risk: {result['risk_label']}"
            ),
            AIMessage(content=response_text),
        ],
    }


def redesign_node(state: ManufacturingState) -> dict:
    """
    Reasoning Node — "The Neocortex"

    Called when stress analysis routes to REDESIGN. Uses Gemini Pro to generate
    specific geometric modification suggestions based on hotspot data.
    """
    system_msg = SystemMessage(
        content=(
            "You are a computational geometry expert for FFF 3D printing. "
            "The part has structural stress hotspots that risk failure. "
            "Provide 3-5 specific, actionable geometry modifications. "
            "Format as a numbered list. Be precise (use mm dimensions)."
        )
    )
    human_msg = HumanMessage(
        content=(
            f"Part: {state['part_name']}\n"
            f"Failure probability: {state.get('failure_probability', 'unknown')}\n"
            f"Hotspot centroid: {state.get('hotspot_centroid', 'unknown')}\n"
            f"High-stress vertex %: {state.get('high_stress_vertex_pct', 'unknown')}\n"
            f"Original query: {state['query']}\n"
            "Generate specific redesign suggestions."
        )
    )
    response = _llm(pro=True).invoke([system_msg, human_msg])
    suggestion = response.content.strip()

    _lancedb_log(
        topic=f"redesign suggestions: {state['part_name']}",
        decision=f"Generated {len(suggestion.splitlines())} suggestions",
        content=suggestion,
        category="workflow",
    )

    return {
        "redesign_suggestion": suggestion,
        "current_route": "done",
        "texture_verdict": "BLOCKED_BY_STRESS",
        "messages": [AIMessage(content=f"[Redesign Required]\n{suggestion}")],
    }


def texture_node(state: ManufacturingState) -> dict:
    """
    Texture Pipeline Node — calls the existing VisualizerAgent pipeline
    for one iteration.
    """
    iteration = state.get("texture_iteration", 0) + 1

    try:
        from scripts.pipeline_tools import run_texture_pipeline

        result = run_texture_pipeline(
            part_name=state["part_name"],
            stl_path=state["stl_path"],
        )
        verdict = result.get("verdict", "PENDING")
        u = result.get("uniformity_score", 0.0) or 0.0
        s = result.get("seam_score", 0.0) or 0.0
        b = result.get("beauty_score", 0.0) or 0.0
    except Exception as exc:
        verdict = "PENDING"
        u = s = b = 0.0
        result = {"error": str(exc)}

    _lancedb_log(
        topic=f"texture iter {iteration}: {state['part_name']}",
        decision=f"verdict={verdict} u={u:.3f} s={s:.3f} b={b:.3f}",
        content=json.dumps(result, default=str),
        category="workflow",
    )

    return {
        "texture_iteration": iteration,
        "texture_verdict": verdict,
        "uniformity_score": u,
        "seam_score": s,
        "beauty_score": b,
        "messages": [
            AIMessage(
                content=(
                    f"[Texture iter {iteration}] verdict={verdict} "
                    f"u={u:.3f} s={s:.3f} b={b:.3f}"
                )
            )
        ],
    }


def export_node(state: ManufacturingState) -> dict:
    """Final node — records the outcome, writes Spectral DNA, logs to LanceDB."""
    verdict = state.get("texture_verdict", "UNKNOWN")
    export_path = (
        REPO_ROOT
        / "scripts"
        / "pipeline_exports"
        / f"{state['part_name']}_{state['thread_id'][:8]}.json"
    )
    export_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "part_name": state["part_name"],
        "stl_path": state["stl_path"],
        "query": state["query"],
        "thread_id": state["thread_id"],
        "verdict": verdict,
        "failure_probability": state.get("failure_probability"),
        "risk_label": state.get("risk_label"),
        "uniformity_score": state.get("uniformity_score"),
        "seam_score": state.get("seam_score"),
        "beauty_score": state.get("beauty_score"),
        "redesign_suggestion": state.get("redesign_suggestion"),
        "texture_iterations": state.get("texture_iteration", 0),
        "torch_metadata": state.get("torch_metadata"),
        "langsmith_run_id": state.get("langsmith_run_id"),
        "print_outcome": state.get("print_outcome", "PENDING"),
    }
    export_path.write_text(json.dumps(payload, indent=2, default=str))

    _lancedb_log(
        topic=f"pipeline export: {state['part_name']}",
        decision=f"Final verdict={verdict} print_outcome={payload['print_outcome']}",
        content=json.dumps(payload, default=str),
        category="workflow",
    )

    return {
        "export_path": str(export_path),
        "messages": [AIMessage(content=f"[Export] {verdict} → {export_path}")],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# IV.  Conditional Edges — "The Routing Logic"
# ═══════════════════════════════════════════════════════════════════════════════


def route_by_stress(state: ManufacturingState) -> Literal["redesign", "texture"]:
    """
    Core conditional edge: route to REDESIGN if failure_probability > 0.85,
    otherwise proceed to texture pipeline.

    This is the "Brain-Body Handshake" — PyTorch makes the physical judgment,
    LangGraph routes the symbolic flow.
    """
    fp = state.get("failure_probability", 0.0) or 0.0
    if fp > 0.85:
        return "redesign"
    return "texture"


def quality_gate(state: ManufacturingState) -> Literal["pass", "iterate", "timeout"]:
    """
    Route after texture node: PASS if scores meet threshold, ITERATE if budget
    remains, TIMEOUT if max iterations reached.
    """
    verdict = state.get("texture_verdict", "PENDING")
    iteration = state.get("texture_iteration", 0)
    max_iter = 3  # max texture iterations within the manufacturing graph

    if verdict == "PASS":
        return "pass"
    if iteration >= max_iter:
        return "timeout"
    return "iterate"


# ═══════════════════════════════════════════════════════════════════════════════
# V.  Graph Assembly
# ═══════════════════════════════════════════════════════════════════════════════


def build_manufacturing_graph() -> Any:
    """Compile the Cyber-Physical LangGraph."""
    g = StateGraph(ManufacturingState)

    # Nodes
    g.add_node("stress_analysis", stress_analysis_node)
    g.add_node("redesign", redesign_node)
    g.add_node("texture", texture_node)
    g.add_node("export", export_node)

    # Edges
    g.add_edge(START, "stress_analysis")

    # Conditional: stress → redesign | texture
    g.add_conditional_edges(
        "stress_analysis",
        route_by_stress,
        {"redesign": "redesign", "texture": "texture"},
    )

    # Redesign always goes to export
    g.add_edge("redesign", "export")

    # Texture quality gate: pass/timeout → export; iterate → texture again
    g.add_conditional_edges(
        "texture",
        quality_gate,
        {"pass": "export", "iterate": "texture", "timeout": "export"},
    )

    g.add_edge("export", END)

    return g.compile()


_graph: Any = None


def _get_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_manufacturing_graph()
    return _graph


# ═══════════════════════════════════════════════════════════════════════════════
# VI.  Public Interface
# ═══════════════════════════════════════════════════════════════════════════════


@traceable(
    name="manufacturing-pipeline",
    tags=["manufacturing", "pytorch", "cyber-physical"],
    metadata={"environment": "dev", "project": "qidistudio"},
)
def run_manufacturing_pipeline(
    stl_path: str,
    part_name: str,
    query: str = "Apply optimal texture and verify structural integrity for FFF printing",
    thread_id: str | None = None,
) -> dict:
    """
    Run the full Cyber-Physical manufacturing pipeline.

    1. PyTorch stress analysis → route to REDESIGN or TEXTURE
    2. Texture pipeline (up to 3 iterations)
    3. Export results + LanceDB memory write

    LangSmith traces every step. Export JSON written to scripts/pipeline_exports/.

    Args:
        stl_path:   Absolute path to the STL file.
        part_name:  Human name for the part (used in LanceDB keys).
        query:      What the agent should optimise for.
        thread_id:  Reuse to resume. Auto-generated if None.

    Returns:
        Final ManufacturingState snapshot as dict.
    """
    tid = thread_id or str(uuid.uuid4())
    graph = _get_graph()

    initial_state: ManufacturingState = {
        "stl_path": stl_path,
        "part_name": part_name,
        "query": query,
        "thread_id": tid,
        "messages": [HumanMessage(content=query)],
        "texture_iteration": 0,
        "print_outcome": "PENDING",
    }

    final_state = graph.invoke(initial_state)

    return {
        "verdict": final_state.get("texture_verdict", "UNKNOWN"),
        "risk_label": final_state.get("risk_label", "UNKNOWN"),
        "failure_probability": final_state.get("failure_probability"),
        "uniformity_score": final_state.get("uniformity_score"),
        "seam_score": final_state.get("seam_score"),
        "beauty_score": final_state.get("beauty_score"),
        "texture_iterations": final_state.get("texture_iteration", 0),
        "redesign_suggestion": final_state.get("redesign_suggestion"),
        "export_path": final_state.get("export_path"),
        "thread_id": tid,
        "torch_metadata": final_state.get("torch_metadata"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# VII.  Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _load_stl_vertices(stl_path: str) -> tuple[list[list[float]], list[list[float]]]:
    """
    Extract vertex positions and normals from an ASCII or binary STL.
    Returns (vertices, normals) — both lists of [x, y, z].
    Clamps to 50,000 vertices for inference performance.
    """
    p = Path(stl_path)
    if not p.exists():
        return [[0, 0, 0]], [[0, 0, 1]]

    try:
        # Try numpy-stl first (fast)
        import numpy as np
        from stl import mesh as stl_mesh

        m = stl_mesh.Mesh.from_file(str(p))
        # m.vectors: (N, 3, 3) — N triangles, 3 vertices each, 3 coords
        verts_np = m.vectors.reshape(-1, 3)[:50_000]
        norms_np = np.repeat(m.normals, 3, axis=0)[:50_000]
        return verts_np.tolist(), norms_np.tolist()

    except ImportError:
        pass

    try:
        # Fallback: pyvista
        import pyvista as pv

        mesh = pv.read(str(p))
        pts = mesh.points[:50_000]
        if hasattr(mesh, "point_normals"):
            norms = mesh.point_normals[:50_000]
        else:
            norms = [[0, 0, 1]] * len(pts)
        return pts.tolist(), (norms.tolist() if hasattr(norms, "tolist") else norms)

    except Exception:
        pass

    # Minimal ASCII STL parser
    vertices: list[list[float]] = []
    normals: list[list[float]] = []
    current_normal = [0.0, 0.0, 1.0]
    try:
        for line in p.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("facet normal"):
                parts = line.split()
                current_normal = [float(parts[2]), float(parts[3]), float(parts[4])]
            elif line.startswith("vertex"):
                parts = line.split()
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
                normals.append(current_normal[:])
                if len(vertices) >= 50_000:
                    break
    except Exception:
        pass

    return vertices or [[0, 0, 0]], normals or [[0, 0, 1]]


def _lancedb_log(topic: str, decision: str, content: str, category: str) -> None:
    """Write a learning record to GCS LanceDB (silently ignores errors)."""
    if not _LANCEDB_OK:
        return
    try:
        upsert_learning(
            topic=topic,
            decision=decision,
            content=content,
            category=category,
            source="manufacturing_graph",
        )
    except Exception:
        pass


# ── CLI smoke test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    stl = sys.argv[1] if len(sys.argv) > 1 else "test.stl"
    part = sys.argv[2] if len(sys.argv) > 2 else "test_part"
    result = run_manufacturing_pipeline(stl_path=stl, part_name=part)
    print(json.dumps(result, indent=2, default=str))
