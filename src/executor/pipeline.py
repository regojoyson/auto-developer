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
import subprocess

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
from src.repos.resolver import get_base_branch

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


# ─── Repo Preparation ──────────────────────────────────

def _prepare_repo_for_branch(repo_dir, base_branch, feature_branch=None):
    """Ensure repo is clean and on latest base branch before agent work.

    Steps:
    1. git stash --include-untracked (save any leftover changes)
    2. git checkout <baseBranch>
    3. git fetch origin
    4. git reset --hard origin/<baseBranch>
    5. If feature_branch provided, checkout it (local or remote)

    Args:
        repo_dir: Absolute path to the repo directory.
        base_branch: Base branch name (e.g. "main", "prod").
        feature_branch: Optional feature branch to checkout after pull.
    """
    def run(cmd):
        try:
            result = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
            return result.stdout.strip()
        except Exception:
            return None

    # 1. Stash any uncommitted changes
    stash_result = run(["git", "stash", "--include-untracked"])
    if stash_result and "No local changes" not in stash_result:
        logger.info(f"  Stashed uncommitted changes in {repo_dir}")

    # 2. Checkout base branch
    run(["git", "checkout", base_branch])
    logger.info(f"  Checked out {base_branch}")

    # 3. Fetch latest from origin
    run(["git", "fetch", "origin"])

    # 4. Reset to match origin
    reset_result = run(["git", "reset", "--hard", f"origin/{base_branch}"])
    if reset_result is None:
        run(["git", "pull"])  # fallback
    logger.info(f"  Synced to latest origin/{base_branch}")

    # 5. Checkout feature branch if requested
    if feature_branch:
        local_exists = run(["git", "rev-parse", "--verify", feature_branch])
        remote_exists = run(["git", "rev-parse", "--verify", f"origin/{feature_branch}"])

        if local_exists:
            run(["git", "checkout", feature_branch])
            run(["git", "pull", "origin", feature_branch])
            logger.info(f"  Checked out local branch {feature_branch} (pulled latest)")
        elif remote_exists:
            run(["git", "checkout", "-b", feature_branch, f"origin/{feature_branch}"])
            logger.info(f"  Checked out remote branch {feature_branch}")
        else:
            logger.info(f"  Feature branch {feature_branch} not found yet (will be created by agent)")


# ─── Logging ────────────────────────────────────────────

def _log_phase(issue_key, phase_label, message):
    """Log a phase message to both the logger and the output handlers (dashboard)."""
    display = PHASE_NAMES.get(phase_label, phase_label)
    formatted = f"[{display}] {message}"
    logger.info(f"{issue_key}: {formatted}")

    # Also write to output handlers so it appears in dashboard logs
    handlers = get_output_handlers()
    handlers.on_output(issue_key, "orchestrator", f"\n{'='*60}", "stdout")
    handlers.on_output(issue_key, "orchestrator", f"  {display}: {message}", "stdout")
    handlers.on_output(issue_key, "orchestrator", f"{'='*60}\n", "stdout")


def _log_step(issue_key, message):
    """Log a pipeline step (not tied to a specific phase)."""
    logger.info(f"{issue_key}: {message}")
    handlers = get_output_handlers()
    handlers.on_output(issue_key, "orchestrator", f"  >> {message}", "stdout")


# ─── Result Parsing ─────────────────────────────────────

def _extract_pipeline_result(agent_output):
    """Extract the __PIPELINE_RESULT__ JSON from agent stdout."""
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
    return bool(pipeline_result and pipeline_result.get("blocked"))


def _extract_blocked_reason(result):
    """Extract the blocked reason from agent output."""
    pipeline_result = _extract_pipeline_result(result.get("output", ""))
    if pipeline_result:
        return pipeline_result.get("reason", "No reason provided")
    return "Unknown reason"


# ─── Best-Effort External Calls ─────────────────────────

def _try_transition_issue(issue_key, status_name):
    """Transition issue status (best-effort — logs and continues on failure)."""
    try:
        adapter, _ = get_issue_tracker()
        adapter.transition_issue(issue_key, status_name)
        logger.info(f"{issue_key}: Ticket transitioned to '{status_name}'")
    except Exception as e:
        logger.warning(f"Failed to transition {issue_key} to '{status_name}': {e}")


def _try_add_comment(issue_key, body):
    """Post an issue comment (best-effort — logs and continues on failure)."""
    try:
        adapter, _ = get_issue_tracker()
        adapter.add_comment(issue_key, body)
        logger.info(f"{issue_key}: Comment posted on ticket")
    except Exception as e:
        logger.warning(f"Failed to post comment on {issue_key}: {e}")


def _try_notify_slack(message):
    """Send a Slack notification (best-effort — only if enabled in config)."""
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
            logger.info(f"Slack notification sent")
    except Exception as e:
        logger.warning(f"Failed to send Slack notification: {e}")


# ─── Error Handlers ─────────────────────────────────────

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
    _log_phase(issue_key, "orchestrator:analyze", f"BLOCKED — {reason}")

    _try_add_comment(issue_key,
        f"Pipeline blocked — additional information needed:\n\n{reason}")
    _try_transition_issue(issue_key, statuses["blocked"])
    _try_notify_slack(f"{issue_key} blocked — {reason}")


# ─── Phase Runner ───────────────────────────────────────

def _run_phase(issue_key, branch, agent_name, phase_label, input_data, statuses, repo_dir):
    """Run a single pipeline phase with full tracking and error handling.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name.
        agent_name: Agent to invoke (e.g. "orchestrator").
        phase_label: Label for tracking (e.g. "orchestrator:analyze").
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
        return None

    record_phase_end(branch, 0, "success")
    _log_phase(issue_key, phase_label, "Completed successfully")
    return result


# ─── Main Pipeline ──────────────────────────────────────

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
    logger.info(f"\n{'='*60}")
    logger.info(f"  PIPELINE STARTED: {issue_key}")
    logger.info(f"  Summary: {summary}")
    logger.info(f"  Branch: {branch}")
    logger.info(f"  Base: {base_branch}")
    logger.info(f"  Repo: {repo_dir}")
    logger.info(f"{'='*60}\n")

    # ── Step 1: Prepare repo ─────────────────────────────
    _log_step(issue_key, f"Preparing repo — stash, checkout {base_branch}, pull latest...")
    _prepare_repo_for_branch(repo_dir, base_branch)

    # ── Step 2: Transition ticket to Development (CRITICAL — pipeline stops on failure)
    _log_step(issue_key, f"Transitioning ticket to '{statuses['development']}'...")
    try:
        adapter, _ = get_issue_tracker()
        adapter.transition_issue(issue_key, statuses["development"])
        _log_step(issue_key, f"Ticket transitioned to '{statuses['development']}' successfully")
    except Exception as e:
        error_msg = str(e)
        _log_step(issue_key, f"CRITICAL: Failed to transition ticket — {error_msg}")
        logger.error(f"{issue_key}: Cannot transition to '{statuses['development']}': {error_msg}")
        transition_state(branch, "failed", error={
            "phase": "analyzing",
            "agent": "pipeline",
            "message": f"Failed to transition ticket to '{statuses['development']}': {error_msg}",
        })
        _try_notify_slack(f"{issue_key} pipeline failed — could not transition ticket to '{statuses['development']}'")
        return

    # ── Step 3: Phase 1 — Analyze ────────────────────────
    # Agent reads ticket, creates feature branch, writes TICKET.md, posts analysis comment
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

    # ── Step 4: Phase 2 — Plan ───────────────────────────
    # Brainstorm agent explores codebase, writes PLAN.md, posts plan comment
    _log_step(issue_key, "Transitioning state: analyzing → planning")
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

    # ── Step 5: Prepare repo for implementation ──────────
    # Checkout the feature branch locally so developer agent can work
    _log_step(issue_key, "Transitioning state: planning → developing")
    transition_state(branch, "developing")
    _log_step(issue_key, f"Checking out feature branch {branch} for implementation...")
    _prepare_repo_for_branch(repo_dir, base_branch, feature_branch=branch)

    # ── Step 6: Phase 3 — Implement ─────────────────────
    # Developer agent writes code, commits, pushes, creates MR/PR
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

    # ── Step 7: Complete — awaiting review ───────────────
    _log_step(issue_key, "Transitioning state: developing → awaiting-review")
    transition_state(branch, "awaiting-review")
    _log_step(issue_key, f"Transitioning ticket to '{statuses['done']}'...")
    _try_transition_issue(issue_key, statuses["done"])
    _try_add_comment(issue_key, f"Implementation completed for {issue_key}. MR created. Awaiting review.")
    _try_notify_slack(f"MR created for {issue_key}")

    logger.info(f"\n{'='*60}")
    logger.info(f"  PIPELINE COMPLETED: {issue_key}")
    logger.info(f"  State: awaiting-review")
    logger.info(f"  Branch: {branch}")
    logger.info(f"{'='*60}\n")


# ─── Rework Pipeline ───────────────────────────────────

def run_rework_phases(issue_key, branch, pr_id, statuses, repo_dir):
    """Drive the rework loop: parse feedback -> apply fixes -> awaiting-review.

    Uses the SAME feature branch as the original implementation.
    Runs synchronously in a background thread.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name (same branch as original MR/PR).
        pr_id: PR/MR identifier.
        statuses: Dict with keys: trigger, development, done, blocked.
        repo_dir: Absolute path to the target repo directory.
    """
    state = get_state(branch)
    rework_num = (state.get("reworkCount", 0) if state else 0) + 1

    logger.info(f"\n{'='*60}")
    logger.info(f"  REWORK STARTED: {issue_key} (iteration {rework_num})")
    logger.info(f"  Branch: {branch} (same as original MR)")
    logger.info(f"  PR/MR: {pr_id}")
    logger.info(f"  Repo: {repo_dir}")
    logger.info(f"{'='*60}\n")

    # ── Step 1: Prepare repo — checkout the SAME feature branch ──
    base_branch = get_base_branch()
    _log_step(issue_key, f"Checking out feature branch {branch} (same branch as MR)...")
    _prepare_repo_for_branch(repo_dir, base_branch, feature_branch=branch)

    # ── Step 2: Transition ticket to Development (CRITICAL — rework stops on failure)
    _log_step(issue_key, f"Transitioning ticket to '{statuses['development']}'...")
    try:
        adapter, _ = get_issue_tracker()
        adapter.transition_issue(issue_key, statuses["development"])
        _log_step(issue_key, f"Ticket transitioned to '{statuses['development']}' successfully")
    except Exception as e:
        error_msg = str(e)
        _log_step(issue_key, f"CRITICAL: Failed to transition ticket — {error_msg}")
        logger.error(f"{issue_key}: Cannot transition to '{statuses['development']}': {error_msg}")
        transition_state(branch, "failed", error={
            "phase": "reworking",
            "agent": "pipeline",
            "message": f"Failed to transition ticket to '{statuses['development']}': {error_msg}",
        })
        _try_notify_slack(f"{issue_key} rework failed — could not transition ticket to '{statuses['development']}'")
        return

    _log_step(issue_key, "Transitioning state: awaiting-review → reworking")
    transition_state(branch, "reworking")

    # ── Step 3: Parse review feedback ────────────────────
    # Feedback parser reads MR comments, writes FEEDBACK.md
    _log_phase(issue_key, "feedback-parser", "Parsing review comments from MR...")
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
        _log_phase(issue_key, "feedback-parser", "FEEDBACK.md written successfully")
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, "feedback-parser",
            {"success": False, "error": str(e)}, statuses)
        return

    # ── Step 4: Apply rework fixes ───────────────────────
    # Developer agent reads FEEDBACK.md, applies changes, commits, pushes
    _log_phase(issue_key, "orchestrator:rework", f"Applying review feedback (iteration {rework_num})...")
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
        _log_phase(issue_key, "orchestrator:rework", "Rework changes committed and pushed")
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(issue_key, branch, "orchestrator:rework",
            {"success": False, "error": str(e)}, statuses)
        return

    # ── Step 5: Complete — back to awaiting review ───────
    _log_step(issue_key, "Transitioning state: reworking → awaiting-review")
    transition_state(branch, "awaiting-review")
    _log_step(issue_key, f"Transitioning ticket to '{statuses['done']}'...")
    _try_transition_issue(issue_key, statuses["done"])
    _try_add_comment(issue_key, f"Rework iteration {rework_num} completed for {issue_key}. Awaiting re-review.")
    _try_notify_slack(f"Rework completed for {issue_key} (iteration {rework_num})")

    logger.info(f"\n{'='*60}")
    logger.info(f"  REWORK COMPLETED: {issue_key} (iteration {rework_num})")
    logger.info(f"  State: awaiting-review")
    logger.info(f"  Branch: {branch}")
    logger.info(f"{'='*60}\n")
