"""
Pipeline phase runner.

Drives the ticket lifecycle phase-by-phase: analyze -> plan -> implement -> review.
Each phase invokes an agent, checks the result, and transitions state.
Jira/Slack calls are best-effort (logged on failure, never block the pipeline).

Usage:
    from src.executor.pipeline import run_pipeline_phases, run_rework_phases

    # Called from route handlers in a background thread:
    threading.Thread(target=run_pipeline_phases, args=(...), daemon=True).start()
"""

import json
import logging

from src.executor.runner import run_agent
from src.state.manager import (
    get_state,
    transition_state,
    record_phase_start,
    record_phase_end,
)
from src.providers.issue_tracker import get_issue_tracker
from src.providers.notification import get_notification
from src.providers.output_handler import get_output_handlers

logger = logging.getLogger(__name__)

# Marker that agents write to stdout to communicate structured results.
RESULT_MARKER = "__PIPELINE_RESULT__:"

# Phase display names for clear logging
PHASE_NAMES = {
    "orchestrator:analyze": "Phase 1 — Analyze",
    "orchestrator:plan": "Phase 2 — Plan",
    "orchestrator:implement": "Phase 3 — Implement",
    "orchestrator:rework": "Rework — Apply Fixes",
    "feedback-parser": "Rework — Parse Feedback",
}


def _log_phase(issue_key, phase_label, message):
    """Log a phase message to both the logger and the output handlers."""
    display = PHASE_NAMES.get(phase_label, phase_label)
    formatted = f"[{display}] {message}"
    logger.info(f"{issue_key}: {formatted}")

    # Also write to the output handlers so it appears in dashboard logs
    handlers = get_output_handlers()
    handlers.on_output(issue_key, phase_label, f"\n{'='*60}", "stdout")
    handlers.on_output(issue_key, phase_label, f"  {display}: {message}", "stdout")
    handlers.on_output(issue_key, phase_label, f"{'='*60}\n", "stdout")


def _extract_pipeline_result(agent_output):
    """Extract the __PIPELINE_RESULT__ JSON from agent stdout.

    Scans agent output for a line starting with the result marker,
    parses the JSON payload, and returns it.

    Args:
        agent_output: Full stdout from the agent process.

    Returns:
        Parsed dict (e.g. {"blocked": false}) or None if no marker found.
    """
    for line in agent_output.split("\n"):
        line = line.strip()
        if line.startswith(RESULT_MARKER):
            try:
                return json.loads(line[len(RESULT_MARKER):])
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse pipeline result: {line}")
    return None


def _is_blocked(result):
    """Check if the agent result indicates a blocked ticket."""
    pipeline_result = _extract_pipeline_result(result.get("output", ""))
    if pipeline_result and pipeline_result.get("blocked"):
        return True
    return False


def _extract_blocked_reason(result):
    """Extract the blocked reason from agent output."""
    pipeline_result = _extract_pipeline_result(result.get("output", ""))
    if pipeline_result:
        return pipeline_result.get("reason", "No reason provided")
    return "Unknown reason"


def _try_transition_issue(issue_key, status_name):
    """Transition issue status (best-effort)."""
    try:
        adapter, _ = get_issue_tracker()
        adapter.transition_issue(issue_key, status_name)
    except Exception as e:
        logger.warning(f"Failed to transition {issue_key} to '{status_name}': {e}")


def _try_add_comment(issue_key, body):
    """Post an issue comment (best-effort)."""
    try:
        adapter, _ = get_issue_tracker()
        adapter.add_comment(issue_key, body)
    except Exception as e:
        logger.warning(f"Failed to post comment on {issue_key}: {e}")


def _try_notify_slack(message):
    """Send a Slack notification (best-effort)."""
    try:
        result = get_notification()
        if result:
            adapter, notif_config = result
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                loop.create_task(adapter.send(message, notif_config))
            else:
                asyncio.run(adapter.send(message, notif_config))
    except Exception as e:
        logger.warning(f"Failed to send Slack notification: {e}")


def _handle_agent_failure(issue_key, branch, agent_name, result, statuses):
    """Handle a non-zero agent exit by transitioning to failed state."""
    error_msg = result.get("error", "unknown error")
    _log_phase(issue_key, agent_name, f"FAILED — {error_msg}")

    current = get_state(branch)
    current_phase = current["state"] if current else "unknown"

    transition_state(branch, "failed", error={
        "phase": current_phase,
        "agent": agent_name,
        "message": error_msg,
    })

    _try_add_comment(issue_key,
        f"Pipeline failed during {PHASE_NAMES.get(agent_name, agent_name)}.\n\nError: {error_msg}\n\nCheck logs for details.")
    _try_notify_slack(f"{issue_key} pipeline failed during {PHASE_NAMES.get(agent_name, agent_name)} — check logs")


def _handle_blocked(issue_key, branch, statuses, result):
    """Handle an agent reporting the ticket is blocked."""
    reason = _extract_blocked_reason(result)
    logger.info(f"Pipeline blocked for {issue_key}: {reason}")

    _try_add_comment(issue_key,
        f"Pipeline blocked — additional information needed:\n\n{reason}")
    _try_transition_issue(issue_key, statuses["blocked"])
    _try_notify_slack(f"{issue_key} blocked — {reason}")


def _run_phase(issue_key, branch, agent_name, phase_label, input_data, statuses, repo_dir):
    """Run a single pipeline phase with full tracking and error handling.

    The phase_label is used as the output handler key, so logs for each
    phase are stored separately (e.g. "orchestrator:analyze", "orchestrator:plan").

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name.
        agent_name: Agent to invoke (e.g. "orchestrator").
        phase_label: Label for tracking and log routing (e.g. "orchestrator:analyze").
        input_data: JSON string input for the agent.
        statuses: Dict of issue status names.
        repo_dir: Working directory for the agent.

    Returns:
        Agent result dict on success, or None if the phase failed/blocked.
    """
    current = get_state(branch)
    record_phase_start(branch, current["state"], phase_label)
    _log_phase(issue_key, phase_label, "Starting...")

    try:
        # Pass phase_label as issue_key suffix so output handler stores per-phase
        result = run_agent(agent_name, input_data, cwd=repo_dir, issue_key=issue_key)
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, phase_label,
            {"success": False, "error": str(e)}, statuses)
        return None

    if not result.get("success"):
        record_phase_end(branch, result.get("exit_code", -1), "failed")
        _handle_agent_failure(issue_key, branch, phase_label, result, statuses)
        return None

    if _is_blocked(result):
        record_phase_end(branch, 0, "blocked")
        _handle_blocked(issue_key, branch, statuses, result)
        _log_phase(issue_key, phase_label, "BLOCKED")
        return None

    record_phase_end(branch, 0, "success")
    _log_phase(issue_key, phase_label, "Completed successfully")
    return result


def run_pipeline_phases(issue_key, branch, summary, project_key, base_branch, statuses, repo_dir):
    """Drive the full pipeline: analyze -> plan -> implement -> awaiting-review.

    Runs synchronously in a background thread. Each phase invokes an agent,
    checks the result, transitions state, and posts issue comments.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name (e.g. "ev-14942_fix_xss").
        summary: Ticket summary text.
        project_key: Project key (e.g. "EV").
        base_branch: Base branch to create feature branch from (e.g. "main").
        statuses: Dict with keys: trigger, development, done, blocked.
        repo_dir: Absolute path to the target repo directory.
    """
    logger.info(f"{'='*60}")
    logger.info(f"  Pipeline started for {issue_key}")
    logger.info(f"  Branch: {branch}")
    logger.info(f"  Repo: {repo_dir}")
    logger.info(f"{'='*60}")

    # Step 1: Transition issue to Development status
    _log_phase(issue_key, "orchestrator:analyze", "Transitioning ticket to Development...")
    _try_transition_issue(issue_key, statuses["development"])

    # Step 2: Analyze phase — read ticket, write TICKET.md, post analysis comment
    analyze_input = json.dumps({
        "action": "analyze",
        "issueKey": issue_key,
        "branch": branch,
        "summary": summary,
        "projectKey": project_key,
        "baseBranch": base_branch,
        "statuses": statuses,
    })
    result = _run_phase(issue_key, branch, "orchestrator", "orchestrator:analyze",
                        analyze_input, statuses, repo_dir)
    if result is None:
        return

    # Step 3: Plan phase — brainstorm agent writes PLAN.md, post plan comment
    transition_state(branch, "planning")
    plan_input = json.dumps({
        "action": "plan",
        "issueKey": issue_key,
        "branch": branch,
        "statuses": statuses,
    })
    result = _run_phase(issue_key, branch, "orchestrator", "orchestrator:plan",
                        plan_input, statuses, repo_dir)
    if result is None:
        return

    # Step 4: Implement phase — developer agent codes, commits, pushes, creates MR
    transition_state(branch, "developing")
    implement_input = json.dumps({
        "action": "implement",
        "issueKey": issue_key,
        "branch": branch,
        "summary": summary,
        "baseBranch": base_branch,
        "statuses": statuses,
    })
    result = _run_phase(issue_key, branch, "orchestrator", "orchestrator:implement",
                        implement_input, statuses, repo_dir)
    if result is None:
        return

    # Step 5: Transition to awaiting-review, update issue to Done
    transition_state(branch, "awaiting-review")
    _log_phase(issue_key, "orchestrator:implement", "Transitioning ticket to Done...")
    _try_transition_issue(issue_key, statuses["done"])
    _try_add_comment(issue_key, f"Implementation completed for {issue_key}. MR created. Awaiting review.")
    _try_notify_slack(f"MR created for {issue_key}")

    logger.info(f"{'='*60}")
    logger.info(f"  Pipeline completed for {issue_key}")
    logger.info(f"{'='*60}")


def run_rework_phases(issue_key, branch, pr_id, statuses, repo_dir):
    """Drive the rework loop: parse feedback -> apply fixes -> awaiting-review.

    Runs synchronously in a background thread.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name.
        pr_id: PR/MR identifier.
        statuses: Dict with keys: trigger, development, done, blocked.
        repo_dir: Absolute path to the target repo directory.
    """
    logger.info(f"{'='*60}")
    logger.info(f"  Rework started for {issue_key}")
    logger.info(f"{'='*60}")

    # Transition issue to Development
    _try_transition_issue(issue_key, statuses["development"])
    transition_state(branch, "reworking")

    # Step 1: Parse feedback
    _log_phase(issue_key, "feedback-parser", "Parsing review comments...")
    record_phase_start(branch, "reworking", "feedback-parser")
    try:
        feedback_input = json.dumps({
            "issueKey": issue_key,
            "branch": branch,
            "prId": pr_id,
        })
        feedback_result = run_agent("feedback-parser", feedback_input, cwd=repo_dir, issue_key=issue_key)
        if not feedback_result.get("success"):
            record_phase_end(branch, feedback_result.get("exit_code", -1), "failed")
            _handle_agent_failure(issue_key, branch, "feedback-parser", feedback_result, statuses)
            return
        record_phase_end(branch, 0, "success")
        _log_phase(issue_key, "feedback-parser", "Feedback parsed successfully")
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, "feedback-parser",
            {"success": False, "error": str(e)}, statuses)
        return

    # Step 2: Apply rework
    _log_phase(issue_key, "orchestrator:rework", "Applying review feedback...")
    record_phase_start(branch, "reworking", "orchestrator:rework")
    try:
        rework_input = json.dumps({
            "action": "rework",
            "issueKey": issue_key,
            "branch": branch,
            "statuses": statuses,
        })
        rework_result = run_agent("orchestrator", rework_input, cwd=repo_dir, issue_key=issue_key)
        if not rework_result.get("success"):
            record_phase_end(branch, rework_result.get("exit_code", -1), "failed")
            _handle_agent_failure(issue_key, branch, "orchestrator:rework", rework_result, statuses)
            return
        record_phase_end(branch, 0, "success")
        _log_phase(issue_key, "orchestrator:rework", "Rework applied successfully")
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, "orchestrator:rework",
            {"success": False, "error": str(e)}, statuses)
        return

    # Step 3: Back to awaiting-review
    transition_state(branch, "awaiting-review")
    _try_transition_issue(issue_key, statuses["done"])
    _try_add_comment(issue_key, f"Rework completed for {issue_key}. Awaiting re-review.")
    _try_notify_slack(f"Rework completed for {issue_key}")

    logger.info(f"{'='*60}")
    logger.info(f"  Rework completed for {issue_key}")
    logger.info(f"{'='*60}")
