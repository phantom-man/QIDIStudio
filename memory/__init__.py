"""
QIDIStudio Persistent Memory Module
====================================
Provides semantic memory persistence for the GitHub Copilot engineering agent.

Architecture:
  - LanceDB  : GCS vector store at gs://qidistudio-lancedb/lancedb — session learnings as embeddings
  - Postgres  : LangGraph checkpoint state (shared with DeepAgents)
  - LangSmith : tracing + system prompt hub

Entry points:
  inject.py  — called by UserPromptSubmit hook; returns relevant memories as context
  extract.py — called by agent (via terminal) after Save This Protocol; stores to LanceDB
"""
