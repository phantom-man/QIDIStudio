import sys
import os

repo_dir = r"c:\Users\User\source\repos\QIDIStudio"
sys.path.insert(0, repo_dir)

from agents.orchestrator import run

try:
    prompt = """
    You are the agent with the largest context window.
    Your task: Retrieve ALL data from our LanceDB persistent memory (table qidistudio_learnings).
    LanceDB is on GCS: gs://qidistudio-lancedb/lancedb (LANCEDB_PATH env var). Use memory.store or lancedb.connect() directly.
    Analyze the entire contents.
    Write a detailed executive summary of the project's current state: 
    - What is the architecture? 
    - What are the major recent accomplishments (e.g., C++ modernization, texture pipeline, etc.)?
    - What are the current open goals/issues?
    """

    result = run(prompt, thread_id="exec-summary-001")

    with open("exec_summary_out.txt", "w", encoding="utf-8") as f:
        f.write(str(result))
    print("FINISHED")
except Exception as e:
    import traceback

    with open("exec_summary_error.txt", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    print("ERROR")
