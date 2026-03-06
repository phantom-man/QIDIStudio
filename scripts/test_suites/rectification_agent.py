"""
scripts/test_suites/rectification_agent.py — Autonomous failure rectification.

When a test FAILS, the RectificationAgent is invoked to:
  1. Describe the failure precisely (error message + context)
  2. Dispatch a dev_fleet task: "Fix the following test failure: ..."
  3. Re-run the test (up to MAX_ATTEMPTS)
  4. If the fix produces a PASS → record as fixed
  5. If MAX_ATTEMPTS exhausted → mark as BLOCKED

This module never interacts with the user. It runs entirely autonomously,
delegates implementation to the dev_fleet coder/tester teams, and reads
their output from Postgres.

Architecture
────────────
  TestRunner (phd_test_pipeline)
      │
      ├── FAIL detected
      │
      └─► RectificationAgent.attempt_fix(result, test_func)
               │
               ├── build task_string from failure context
               │
               ├── spawn dev_fleet via subprocess (non-blocking, redirect to file)
               │
               └── wait for DONE signal → re-run test → return new TestResult
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"
MAX_ATTEMPTS = 3
FLEET_TIMEOUT_S = 300  # 5 minutes per rectification attempt


class RectificationAgent:
    """
    Autonomous code-fix loop backed by the dev_fleet coder/tester teams.

    Parameters
    ----------
    dry_run : bool
        If True, log the task string but do NOT actually invoke dev_fleet.
        Useful for testing the rectification harness itself.
    """

    def __init__(self, dry_run: bool = False, verbose: bool = True) -> None:
        self.dry_run = dry_run
        self.verbose = verbose
        self._attempt_log: list[dict] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def attempt_fix(
        self,
        group_id: str,
        test_id: str,
        test_name: str,
        error_msg: str,
        test_func: Callable[[], bool],
        current_attempt: int = 1,
    ) -> tuple[bool, str | None, int]:
        """
        Try to auto-fix a failing test.

        Returns
        -------
        (passed, error_msg_or_None, final_attempt_number)
        """
        if current_attempt > MAX_ATTEMPTS:
            self._log(f"[BLOCKED] {test_id} exhausted {MAX_ATTEMPTS} attempts")
            return False, f"Exhausted {MAX_ATTEMPTS} rectification attempts. Last error: {error_msg}", current_attempt

        self._log(f"[FIX#{current_attempt}] Starting rectification for {test_id}")

        # Build a precise task string for the dev fleet
        task_string = self._build_task(group_id, test_id, test_name, error_msg, current_attempt)
        self._log(f"  Task: {task_string[:120]}...")

        fix_success = self._dispatch_fleet(task_string, test_id, current_attempt)
        if not fix_success and not self.dry_run:
            self._log(f"  Dev fleet dispatch failed or timed out")

        # Re-run the test regardless of fleet success (maybe it self-healed or was a transient error)
        try:
            passed = test_func()
            if passed:
                self._log(f"  ✅ FIXED: {test_id} passes after attempt #{current_attempt}")
                return True, None, current_attempt
            else:
                error_after = "Test returned False after rectification"
                self._log(f"  ❌ Still failing: {test_id}")
        except Exception as exc:  # noqa: BLE001
            error_after = str(exc)[:2000]
            self._log(f"  ❌ Still failing with exception: {error_after[:120]}")

        # Recurse for next attempt
        return self.attempt_fix(
            group_id=group_id,
            test_id=test_id,
            test_name=test_name,
            error_msg=error_after,
            test_func=test_func,
            current_attempt=current_attempt + 1,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_task(
        self,
        group_id: str,
        test_id: str,
        test_name: str,
        error_msg: str,
        attempt: int,
    ) -> str:
        """
        Construct a dev_fleet task string describing the failure precisely.
        Follows the "VERB + SUBJECT + CONSTRAINT + OUTPUT FORMAT" pattern from
        the Agentic Fleet Protocol in copilot-instructions.md.
        """
        context_snippets = {
            "A": "Python import or smoke test. Check that the module exists and its dependencies are installed.",
            "B": "LangGraph agent compilation. Verify all imports, tools, and graph edges are valid.",
            "C": "Pipeline end-to-end test. Check that all inputs exist and the pipeline runs without errors.",
            "D": "TypeScript/VS Code extension test. Run npm test and fix any compilation or assertion errors.",
            "E": "C++/CMake build test. Fix compilation errors or missing CMakeLists targets.",
            "F": "Visual quality test. The rendering or texture output failed Gemini Vision inspection.",
            "G": "Database integrity test. Verify Postgres and LanceDB are accessible and have expected data.",
            "H": "API connectivity test. Verify that the required API key and endpoint are reachable.",
            "I": "File/asset existence test. The expected file or directory does not exist.",
        }
        context = context_snippets.get(group_id, "general test failure")

        return (
            f"RECTIFY test failure (attempt {attempt}/{MAX_ATTEMPTS}): "
            f"Test '{test_id}' ({test_name}) in group {group_id} ({context}) "
            f"failed with error: {error_msg[:800]}. "
            f"Diagnose the root cause, implement the minimum fix needed to make the test pass, "
            f"and output the patched code snippet(s). "
            f"Do NOT change test assertions — fix the implementation being tested."
        )

    def _dispatch_fleet(self, task_string: str, test_id: str, attempt: int) -> bool:
        """
        Invoke dev_fleet.py via subprocess (fire-and-forget with DONE sentinel).
        Returns True if the fleet completed within FLEET_TIMEOUT_S.
        """
        if self.dry_run:
            self._log(f"  [DRY-RUN] Would dispatch: {task_string[:80]}...")
            return True

        out_file = REPO_ROOT / "agents" / f"_rect_{test_id}_{attempt}.txt"
        cmd = [
            str(MEMORY_PY),
            "-B",
            str(REPO_ROOT / "agents" / "dev_fleet.py"),
            task_string,
        ]
        try:
            # Non-blocking: redirect stdout+stderr to file, add DONE sentinel
            with open(out_file, "w") as fh:
                proc = subprocess.Popen(
                    cmd,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    cwd=str(REPO_ROOT),
                    text=True,
                )
        except Exception as exc:  # noqa: BLE001
            self._log(f"  Failed to spawn dev_fleet: {exc}")
            return False

        # Poll for DONE sentinel or timeout
        sentinel_script = (
            f"echo DONE >> {out_file}"
        )
        deadline = time.monotonic() + FLEET_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(5)
            if proc.poll() is not None:
                # Process finished — append DONE manually
                with open(out_file, "a") as fh:
                    fh.write("\nDONE\n")
                return True
            # Check file for DONE
            try:
                content = out_file.read_text(encoding="utf-8", errors="replace")
                if "DONE" in content or "final_response" in content.lower():
                    return True
            except Exception:
                pass

        self._log(f"  [TIMEOUT] dev_fleet timeout after {FLEET_TIMEOUT_S}s")
        try:
            proc.terminate()
        except Exception:
            pass
        return False

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[RectificationAgent] {msg}")
        self._attempt_log.append({"ts": time.time(), "msg": msg})
