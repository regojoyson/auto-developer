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
    find_state_by_issue_key,
)
from src.config import config as app_config
from src.providers.issue_tracker import get_issue_tracker, is_api_mode
from src.providers.notification import get_notification
from src.providers.output_handler import get_output_handlers
from src.repos.resolver import get_base_branch
from src.executor.phase_scope import (
    ANALYZE_SCOPE,
    PLAN_SCOPE,
    IMPLEMENT_SCOPE,
    REWORK_SCOPE,
    FEEDBACK_PARSER_SCOPE,
    REPO_PICKER_SCOPE,
)
from src.executor.pipeline_git import (
    create_remote_branch,
    commit_local_file_via_api,
    push_local_branch,
    create_merge_request,
)
from src.providers.git_provider import get_git_provider

logger = logging.getLogger(__name__)

# Marker that agents write to stdout to communicate structured results.
RESULT_MARKER = "__PIPELINE_RESULT__:"

# Phase display names for clear logging
PHASE_NAMES = {
    "phase:repo-picker": "Phase 0 — Repo Selection",
    "phase:analyze": "Phase 1 — Analyze",
    "phase:plan": "Phase 2 — Plan",
    "phase:implement": "Phase 3 — Implement",
    "phase:rework": "Rework — Apply Fixes",
    "feedback-parser": "Rework — Parse Feedback",
}


def _os_path_has_git(path: str) -> bool:
    """Return True if ``path`` contains a .git directory (i.e. is a git repo)."""
    from pathlib import Path
    return (Path(path) / ".git").exists()


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
    display = PHASE_NAMES.get(phase_label)
    if not display:
        # Dynamic per-repo label: "phase:<repo>:<action>"
        parts = phase_label.split(":")
        if len(parts) == 3 and parts[0] == "phase":
            repo, action = parts[1], parts[2]
            pretty_action = {
                "analyze": "Analyze",
                "plan": "Plan",
                "implement": "Implement",
                "rework": "Rework",
            }.get(action, action.title())
            display = f"{pretty_action} ({repo})"
        else:
            display = phase_label
    formatted = f"[{display}] {message}"
    logger.info(f"{issue_key}: {formatted}")

    # Also write to output handlers so it appears in dashboard logs
    handlers = get_output_handlers()
    handlers.on_output(issue_key, "pipeline", f"\n{'='*60}", "stdout")
    handlers.on_output(issue_key, "pipeline", f"  {display}: {message}", "stdout")
    handlers.on_output(issue_key, "pipeline", f"{'='*60}\n", "stdout")


def _log_step(issue_key, message):
    """Log a pipeline step (not tied to a specific phase)."""
    logger.info(f"{issue_key}: {message}")
    handlers = get_output_handlers()
    handlers.on_output(issue_key, "pipeline", f"  >> {message}", "stdout")


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
    """Transition issue status (best-effort — logs on failure, never raises)."""
    try:
        adapter, _ = get_issue_tracker()
        adapter.transition_issue(issue_key, status_name)
        logger.info(f"{issue_key}: Ticket transitioned to '{status_name}'")
    except Exception as e:
        logger.warning(f"Failed to transition {issue_key} to '{status_name}': {e}")


def _try_add_comment(issue_key, body):
    """Post an issue comment (best-effort — logs on failure, never raises)."""
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


# Public alias so webhook routes can post best-effort ticket comments
# without importing a private helper.
try_add_comment = _try_add_comment
try_notify_slack = _try_notify_slack


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


def _handle_blocked(issue_key, branch, statuses, result, phase_label="phase:analyze"):
    """Handle an agent reporting the ticket is blocked.

    Transitions the pipeline state machine to "blocked" so a Jira comment
    webhook can later resume from planning. Posts a Jira comment with the
    blocker reason and sets the Jira ticket status to the configured
    blockedStatus.
    """
    reason = _extract_blocked_reason(result)
    _log_phase(issue_key, phase_label, f"BLOCKED — {reason}")

    # Record blocked state so the comment-webhook can resume later.
    try:
        current = get_state(branch)
        if current and current["state"] in ("analyzing", "planning"):
            transition_state(branch, "blocked", error={
                "phase": current["state"],
                "agent": phase_label,
                "message": reason,
            })
    except Exception as e:
        logger.warning(f"Failed to record blocked state for {branch}: {e}")

    _try_add_comment(issue_key,
        f"Pipeline blocked — additional information needed:\n\n{reason}\n\n"
        f"_Reply to this ticket with the missing details and the pipeline will resume._")
    _try_transition_issue(issue_key, statuses["blocked"])
    _try_notify_slack(f"{issue_key} blocked — {reason}")


# ─── Phase Runner ───────────────────────────────────────

def _run_phase(
    issue_key, branch, agent_name, phase_label,
    input_data, statuses, repo_dir, *, phase_scope=None,
):
    """Run a single pipeline phase with full tracking and error handling.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name.
        agent_name: Agent to invoke (e.g. "analyze").
        phase_label: Label for tracking (e.g. "phase:analyze").
        input_data: JSON string input for the agent.
        statuses: Dict of issue status names.
        repo_dir: Working directory for the agent.
        phase_scope: Optional :class:`PhaseScope` restricting agent tools.

    Returns:
        Agent result dict on success, or None if the phase failed/blocked.
    """
    current = get_state(branch)
    record_phase_start(branch, current["state"], phase_label)
    _log_phase(issue_key, phase_label, "Starting...")

    try:
        result = run_agent(
            agent_name, input_data,
            cwd=repo_dir, issue_key=issue_key,
            phase_scope=phase_scope,
        )
    except Exception as e:
        record_phase_end(branch, -1, "failed")
        _handle_agent_failure(
            issue_key, branch, phase_label,
            {"success": False, "error": str(e)}, statuses,
        )
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


def _run_repo_phase(
    issue_key, branch, agent_name, phase_label,
    input_data, statuses, repo_dir, *, phase_scope=None,
):
    """Run a single phase for a single repo in fan-out mode.

    Unlike ``_run_phase``, this does NOT transition the overall pipeline
    to "failed" on per-repo agent errors — the caller is responsible for
    recording the failure on the per-repo sub-state.
    """
    _log_phase(issue_key, phase_label, "Starting...")
    try:
        result = run_agent(
            agent_name, input_data,
            cwd=repo_dir, issue_key=issue_key,
            phase_scope=phase_scope,
        )
    except Exception as e:
        _log_phase(issue_key, phase_label, f"EXCEPTION — {e}")
        return None

    if not result.get("success"):
        _log_phase(issue_key, phase_label, f"FAILED — exit={result.get('exit_code')} err={result.get('error')}")
        return None

    if _is_blocked(result):
        reason = _extract_blocked_reason(result)
        _log_phase(issue_key, phase_label, f"BLOCKED — {reason}")
        return None

    _log_phase(issue_key, phase_label, "Completed successfully")
    return result


# ─── Per-Repo Pipeline ──────────────────────────────────

def _read_repo_file(repo_dir: str, file_path: str) -> str | None:
    """Read a file the agent wrote to the repo working dir, if present."""
    from pathlib import Path as _P
    full = _P(repo_dir) / file_path
    if not full.exists():
        return None
    try:
        return full.read_text(encoding="utf-8")
    except Exception:
        return None


def _comment_with_prefix(issue_key: str, repo_name: str, multi_repo: bool,
                        title: str, body: str) -> None:
    """Post a Jira comment for a phase output, scoped to a repo when in multi-repo."""
    if not body:
        return
    header = f"**{title} — {repo_name}**" if multi_repo else f"**{title}**"
    _try_add_comment(issue_key, f"{header}\n\n{body}")


def _run_analyze_for_repo(
    issue_key, branch, base_branch, summary, statuses,
    repo_name, repo_dir, ticket_data, api_mode,
) -> dict:
    """Phase 1 for one repo: prepare base, run analyze, return TICKET.md content.

    Runs with the local repo checked out to the base branch — no remote
    branch is created yet. The ticket-status transition to Development
    happens in the orchestrator, AFTER analyses succeed and summaries are
    posted to Jira.

    Returns:
        Dict with keys:
            success: bool
            blocked: bool — True if the agent reported blocked=true
            blocked_reason: str | None
            ticket_md: str | None — contents of TICKET.md the agent wrote
            error: str | None
    """
    from src.state.manager import update_repo_sub_state

    try:
        update_repo_sub_state(branch, repo_name, "preparing")
        _prepare_repo_for_branch(repo_dir, base_branch)

        update_repo_sub_state(branch, repo_name, "analyzing")
        analyze_payload = {
            "issueKey": issue_key,
            "branch": branch,
            "summary": summary,
            "baseBranch": base_branch,
            "statuses": statuses,
            "apiMode": api_mode,
            "repo": repo_name,
        }
        if ticket_data:
            analyze_payload["ticketData"] = ticket_data

        phase_label = f"phase:{repo_name}:analyze"
        _log_phase(issue_key, phase_label, "Starting...")
        try:
            result = run_agent(
                "analyze", json.dumps(analyze_payload),
                cwd=repo_dir, issue_key=issue_key,
                phase_scope=ANALYZE_SCOPE,
            )
        except Exception as e:
            _log_phase(issue_key, phase_label, f"EXCEPTION — {e}")
            update_repo_sub_state(branch, repo_name, "failed", error=str(e))
            return {"success": False, "blocked": False, "blocked_reason": None,
                    "ticket_md": None, "error": str(e)}

        if not result.get("success"):
            err = result.get("error") or f"exit {result.get('exit_code')}"
            _log_phase(issue_key, phase_label, f"FAILED — {err}")
            update_repo_sub_state(branch, repo_name, "failed", error=err)
            return {"success": False, "blocked": False, "blocked_reason": None,
                    "ticket_md": None, "error": err}

        if _is_blocked(result):
            reason = _extract_blocked_reason(result)
            _log_phase(issue_key, phase_label, f"BLOCKED — {reason}")
            return {"success": False, "blocked": True, "blocked_reason": reason,
                    "ticket_md": None, "error": None}

        _log_phase(issue_key, phase_label, "Completed successfully")
        ticket_md = _read_repo_file(repo_dir, "TICKET.md")
        return {"success": True, "blocked": False, "blocked_reason": None,
                "ticket_md": ticket_md, "error": None}

    except Exception as e:
        err = str(e)
        _log_step(issue_key, f"[{repo_name}] analyze failed: {err}")
        update_repo_sub_state(branch, repo_name, "failed", error=err)
        return {"success": False, "blocked": False, "blocked_reason": None,
                "ticket_md": None, "error": err}


def _run_impl_for_repo(
    issue_key, branch, base_branch, summary, statuses,
    repo_name, repo_dir, api_mode, multi_repo,
) -> dict:
    """Phases 2+3 for one repo: create branch, plan, post PLAN comment,
    implement, push, create MR.

    Assumes analyze already ran and wrote TICKET.md to the working dir.
    Commits TICKET.md to the freshly-created feature branch before
    running plan.

    Returns:
        Dict with keys:
            success: bool
            blocked: bool
            blocked_reason: str | None
            prId: int | None
            mrUrl: str | None
            error: str | None
    """
    from src.state.manager import update_repo_sub_state
    import os as _os

    try:
        git_adapter, _ = get_git_provider()
        git_api = git_adapter.create_api(dict(_os.environ), repo_dir=repo_dir)

        # Create the remote branch now (after analyze) and commit TICKET.md.
        create_remote_branch(git_api, branch=branch, base=base_branch)
        if _read_repo_file(repo_dir, "TICKET.md"):
            commit_local_file_via_api(
                git_api, repo_dir=repo_dir, branch=branch,
                file_path="TICKET.md",
                message=f"docs({issue_key}): add ticket context",
            )

        # ── Phase 2 — Plan ──────────────────────────────
        update_repo_sub_state(branch, repo_name, "planning")
        plan_input = json.dumps({
            "issueKey": issue_key,
            "branch": branch,
            "repo": repo_name,
        })
        phase_label = f"phase:{repo_name}:plan"
        _log_phase(issue_key, phase_label, "Starting...")
        try:
            result = run_agent(
                "plan", plan_input,
                cwd=repo_dir, issue_key=issue_key,
                phase_scope=PLAN_SCOPE,
            )
        except Exception as e:
            _log_phase(issue_key, phase_label, f"EXCEPTION — {e}")
            update_repo_sub_state(branch, repo_name, "failed", error=str(e))
            return {"success": False, "blocked": False, "blocked_reason": None,
                    "prId": None, "mrUrl": None, "error": str(e)}

        if not result.get("success"):
            err = result.get("error") or f"exit {result.get('exit_code')}"
            _log_phase(issue_key, phase_label, f"FAILED — {err}")
            update_repo_sub_state(branch, repo_name, "failed", error=err)
            return {"success": False, "blocked": False, "blocked_reason": None,
                    "prId": None, "mrUrl": None, "error": err}

        if _is_blocked(result):
            reason = _extract_blocked_reason(result)
            _log_phase(issue_key, phase_label, f"BLOCKED — {reason}")
            return {"success": False, "blocked": True, "blocked_reason": reason,
                    "prId": None, "mrUrl": None, "error": None}

        _log_phase(issue_key, phase_label, "Completed successfully")

        # Post PLAN.md to Jira before committing it to the branch.
        plan_md = _read_repo_file(repo_dir, "PLAN.md")
        if plan_md:
            _comment_with_prefix(issue_key, repo_name, multi_repo,
                                 "Implementation Plan", plan_md)
            commit_local_file_via_api(
                git_api, repo_dir=repo_dir, branch=branch,
                file_path="PLAN.md",
                message=f"docs({issue_key}): add implementation plan",
            )

        # ── Phase 3 — Implement ─────────────────────────
        update_repo_sub_state(branch, repo_name, "developing")
        _prepare_repo_for_branch(repo_dir, base_branch, feature_branch=branch)
        implement_input = json.dumps({
            "issueKey": issue_key,
            "branch": branch,
            "repo": repo_name,
        })
        result = _run_repo_phase(
            issue_key, branch, "implement",
            f"phase:{repo_name}:implement",
            implement_input, statuses, repo_dir,
            phase_scope=IMPLEMENT_SCOPE,
        )
        if result is None:
            raise RuntimeError("implement phase failed or blocked")

        # Python pushes, creates MR
        push_local_branch(repo_dir, branch)
        mr = create_merge_request(
            git_api,
            source=branch,
            target=base_branch,
            title=f"feat({issue_key}): {summary}",
            description=(
                f"Ticket: {issue_key}\n\n"
                f"Repo: {repo_name}\n\n"
                f"See PLAN.md for the file-level change list."
            ),
        )
        pr_id = mr.get("iid") or mr.get("id") or mr.get("number")
        mr_url = mr.get("web_url") or mr.get("html_url") or mr.get("url") or "(no URL)"
        update_repo_sub_state(
            branch, repo_name, "completed",
            prId=pr_id, mrUrl=mr_url,
        )
        _log_step(issue_key, f"[{repo_name}] MR created: {mr_url}")
        return {"success": True, "blocked": False, "blocked_reason": None,
                "prId": pr_id, "mrUrl": mr_url, "error": None}

    except Exception as e:
        err = str(e)
        _log_step(issue_key, f"[{repo_name}] failed: {err}")
        update_repo_sub_state(branch, repo_name, "failed", error=err)
        return {"success": False, "blocked": False, "blocked_reason": None,
                "prId": None, "mrUrl": None, "error": err}


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
    # Skip repo preparation if repo_dir is a parent dir (no .git) — it will
    # be re-prepared below after the picker chooses a sub-repo.
    if _os_path_has_git(repo_dir):
        _prepare_repo_for_branch(repo_dir, base_branch)
    else:
        _log_step(issue_key, f"{repo_dir} is not a git repo — deferring repo prep until after picker")

    # ── Step 1b: Repo selection (parentDir mode only) ────
    # If config is parentDir AND no component was provided AND no default is
    # set, then repo_dir currently points at the PARENT directory (no git
    # inside). Invoke the repo-picker agent to choose the right sub-repo(s).
    ticket_data = None
    picker_ticket_data = None
    from pathlib import Path as _Path
    if app_config["repo"]["mode"] == "parentDir" and not _os_path_has_git(repo_dir):
        parent = _Path(repo_dir)
        candidates = [
            d.name for d in sorted(parent.iterdir())
            if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists()
        ]
        if not candidates:
            _log_step(issue_key, "CRITICAL: parentDir has no git sub-repos to pick from")
            transition_state(branch, "failed", error={
                "phase": "analyzing", "agent": "pipeline",
                "message": f"No git sub-repos found under {repo_dir}",
            })
            return

        # Read the full ticket now (same as api-mode read_ticket below) so the
        # picker has something to work with.
        picker_ticket = ticket_data
        if picker_ticket is None:
            try:
                adapter_tmp, _ = get_issue_tracker()
                picker_ticket = adapter_tmp.read_issue(issue_key)
                # Cache for later so Step 3 (API mode) doesn't need to re-read.
                ticket_data = picker_ticket
            except Exception as e:
                logger.warning(f"{issue_key}: could not read ticket for picker — {e}")
                picker_ticket = {"summary": summary, "description": ""}
        picker_ticket_data = picker_ticket  # reused below

        picker_input = json.dumps({
            "issueKey": issue_key,
            "summary": picker_ticket.get("summary", summary),
            "description": picker_ticket.get("description", ""),
            "acceptanceCriteria": picker_ticket.get("acceptance_criteria", []),
            "parentDir": str(parent),
            "candidates": candidates,
        })

        _log_step(issue_key, f"Invoking repo-picker over {len(candidates)} candidates...")
        picker_result = _run_phase(
            issue_key, branch, "repo-picker", "phase:repo-picker",
            picker_input, statuses, repo_dir,
            phase_scope=REPO_PICKER_SCOPE,
        )
        if picker_result is None:
            return  # blocked / failed — already handled by _run_phase

        pipeline_result = _extract_pipeline_result(picker_result.get("output", ""))
        # Accept new list format OR legacy single-repo format for safety.
        chosen_repos = None
        if pipeline_result:
            if isinstance(pipeline_result.get("repos"), list):
                chosen_repos = [r for r in pipeline_result["repos"] if r in candidates]
            elif pipeline_result.get("repo") in candidates:
                chosen_repos = [pipeline_result["repo"]]
        if not chosen_repos:
            _log_step(issue_key, f"CRITICAL: picker returned no valid repos: {pipeline_result!r}")
            transition_state(branch, "failed", error={
                "phase": "analyzing", "agent": "pipeline",
                "message": f"Repo-picker returned no valid repo: {pipeline_result!r}",
            })
            return

        _log_step(issue_key, f"Picker chose: {chosen_repos}")
        from src.state.manager import set_state_repos
        set_state_repos(branch, [
            {"name": name, "path": str(parent / name)} for name in chosen_repos
        ])
        # Keep repo_dir as a reasonable default (first picked repo) in case
        # anything downstream still reads it.
        repo_dir = str(parent / chosen_repos[0])

    # If we skipped the picker (component was supplied OR mode != parentDir),
    # ensure state.repos reflects the single repo we'll work on.
    _ensure_state = get_state(branch)
    if _ensure_state and not _ensure_state.get("repos"):
        from src.state.manager import set_state_repos
        set_state_repos(branch, [{
            "name": _Path(repo_dir).name,
            "path": repo_dir,
        }])

    # ── Read ticket once (used by all repos) ────────────
    if ticket_data is None and picker_ticket_data is not None:
        ticket_data = picker_ticket_data
    if ticket_data is None and is_api_mode():
        try:
            adapter_tmp, _ = get_issue_tracker()
            ticket_data = adapter_tmp.read_issue(issue_key)
            _log_step(issue_key, f"Ticket read: {ticket_data.get('summary', '')}")
        except Exception as e:
            logger.warning(f"{issue_key}: could not read ticket — {e}")
            ticket_data = None

    # ── Fan-out setup ───────────────────────────────────
    api_mode = app_config["issue_tracker"]["api_mode"]
    current_state = get_state(branch)
    repos = (current_state.get("repos") if current_state else None) or []
    multi_repo = len(repos) > 1
    _log_step(issue_key, f"Fanning out across {len(repos)} repo(s): {[r['name'] for r in repos]}")

    # ── Pass 1 — Analyze each repo on the base branch ───
    # Runs BEFORE the ticket is moved to Development, so analysis happens
    # in the calm state and its summary lands in Jira before anyone sees
    # the ticket flip to "in progress".
    analyze_results = []
    for repo_entry in repos:
        a = _run_analyze_for_repo(
            issue_key, branch, base_branch, summary, statuses,
            repo_entry["name"], repo_entry["path"], ticket_data, api_mode,
        )
        analyze_results.append((repo_entry, a))

    blocked_any = next(((re, a) for re, a in analyze_results if a["blocked"]), None)
    if blocked_any:
        re, a = blocked_any
        reason = a["blocked_reason"] or "unclear requirements"
        fake_result = {"output": f"{RESULT_MARKER}" + json.dumps({
            "blocked": True,
            "reason": f"[{re['name']}] {reason}" if multi_repo else reason,
        })}
        _handle_blocked(issue_key, branch, statuses, fake_result, phase_label="phase:analyze")
        return

    failed = [(re, a) for re, a in analyze_results if not a["success"]]
    if failed:
        re, a = failed[0]
        err = a["error"] or "analyze failed"
        _handle_agent_failure(issue_key, branch, "phase:analyze",
                              {"success": False, "error": f"[{re['name']}] {err}"},
                              statuses)
        return

    # ── Post analyze summaries to Jira ──────────────────
    for re, a in analyze_results:
        if a["ticket_md"]:
            _comment_with_prefix(issue_key, re["name"], multi_repo,
                                 "Analysis", a["ticket_md"])

    # ── Transition Jira ticket to Development ───────────
    _log_step(issue_key, f"Transitioning ticket to '{statuses['development']}' (via REST API)...")
    try:
        adapter, _ = get_issue_tracker()
        adapter.transition_issue(issue_key, statuses["development"])
        _log_step(issue_key, f"Ticket transitioned to '{statuses['development']}' successfully")
    except Exception as e:
        error_msg = str(e)
        _log_step(issue_key, f"CRITICAL: Failed to transition ticket — {error_msg}")
        logger.error(f"{issue_key}: Cannot transition to '{statuses['development']}': {error_msg}")
        transition_state(branch, "failed", error={
            "phase": "analyzing", "agent": "pipeline",
            "message": f"Failed to transition ticket to '{statuses['development']}': {error_msg}",
        })
        _try_notify_slack(f"{issue_key} pipeline failed — could not transition ticket")
        return

    # ── Advance branch-level state: analyzing → planning → developing ─
    current_state = get_state(branch)
    if current_state and current_state.get("state") == "analyzing":
        transition_state(branch, "planning")
        transition_state(branch, "developing")

    # ── Pass 2 — Create branch + plan + implement + MR per repo ─
    results = _run_impl_fan_out(
        issue_key, branch, base_branch, summary, statuses,
        repos, api_mode, multi_repo,
    )

    # If any repo blocked during plan, the pipeline is already in "blocked"
    # state — don't post completion summary.
    if any(r.get("blocked") for r in results):
        return

    # ── Summary comment + final transitions ─────────────
    ok_repos = [r for r in results if r["success"]]
    err_repos = [r for r in results if not r["success"]]

    if ok_repos:
        lines = [f"Implementation complete for {issue_key}.", ""]
        for r in ok_repos:
            lines.append(f"- **{r['name']}**: {r['mrUrl']}")
        if err_repos:
            lines.append("")
            lines.append("Failed:")
            for r in err_repos:
                lines.append(f"- **{r['name']}**: {r['error']}")
        _try_add_comment(issue_key, "\n".join(lines))
        _try_notify_slack(
            f"MRs created for {issue_key}: " +
            ", ".join(r["mrUrl"] for r in ok_repos)
        )
        _try_transition_issue(issue_key, statuses["done"])
        transition_state(branch, "awaiting-review")
        logger.info(f"  PIPELINE COMPLETED: {issue_key} — {len(ok_repos)} MR(s), {len(err_repos)} failure(s)")
    else:
        error_summary = "; ".join(f"{r['name']}: {r['error']}" for r in err_repos) or "no MRs created"
        _try_add_comment(issue_key, f"Pipeline failed for {issue_key}. Errors: {error_summary}")
        _try_notify_slack(f"{issue_key} pipeline failed: {error_summary}")
        transition_state(branch, "failed", error={
            "phase": "developing", "agent": "pipeline",
            "message": error_summary,
        })


def _run_impl_fan_out(issue_key, branch, base_branch, summary, statuses,
                      repos, api_mode, multi_repo):
    """Run the plan+implement+MR pass across all repos.

    Short-circuits on block: if any repo reports blocked during plan, the
    pipeline transitions to the blocked state and stops further repos.
    """
    results = []
    for repo_entry in repos:
        r = _run_impl_for_repo(
            issue_key, branch, base_branch, summary, statuses,
            repo_entry["name"], repo_entry["path"], api_mode, multi_repo,
        )
        results.append({"name": repo_entry["name"], **r})
        if r.get("blocked"):
            reason = r["blocked_reason"] or "unclear requirements"
            fake_result = {"output": f"{RESULT_MARKER}" + json.dumps({
                "blocked": True,
                "reason": f"[{repo_entry['name']}] {reason}" if multi_repo else reason,
            })}
            _handle_blocked(issue_key, branch, statuses, fake_result,
                            phase_label="phase:plan")
            break
    return results


# ─── Resume from Blocked ───────────────────────────────

def resume_from_blocked(issue_key: str, comment_body: str) -> bool:
    """Resume a blocked pipeline after the human replied with more detail.

    Looks up the existing pipeline state by issue key. Only resumes if the
    pipeline is currently in the "blocked" state. Re-runs the plan +
    implement + MR pass for every repo the picker originally chose —
    analyze is NOT re-run, since the ticket summary/analysis is already
    captured in the earlier Jira comment.

    Args:
        issue_key: Ticket identifier (e.g. "EV-14945").
        comment_body: The new Jira comment that triggered the resume
            (forwarded to the plan agent as additional context).

    Returns:
        True if the pipeline was resumed, False if the ticket wasn't in a
        resumable state.
    """
    state = find_state_by_issue_key(issue_key)
    if not state:
        logger.info(f"{issue_key}: no pipeline state — ignoring comment")
        return False
    if state.get("state") != "blocked":
        logger.info(f"{issue_key}: state is '{state.get('state')}' — not resuming")
        return False

    branch = state["branch"]
    repos = state.get("repos") or []
    if not repos:
        logger.warning(f"{issue_key}: blocked state has no repos — cannot resume")
        return False

    base_branch = get_base_branch()
    tracker_cfg = app_config["issue_tracker"]
    statuses = {
        "trigger": tracker_cfg["trigger_status"],
        "development": tracker_cfg["development_status"],
        "done": tracker_cfg["done_status"],
        "blocked": tracker_cfg["blocked_status"],
    }

    logger.info(f"\n{'='*60}")
    logger.info(f"  RESUMING FROM BLOCKED: {issue_key}")
    logger.info(f"  Branch: {branch}")
    logger.info(f"  Trigger comment: {comment_body[:120]}")
    logger.info(f"{'='*60}\n")

    _try_add_comment(issue_key, "Reply received — resuming pipeline from planning.")
    # blocked → planning
    transition_state(branch, "planning")
    # Move Jira status back to Development while we work.
    _try_transition_issue(issue_key, statuses["development"])
    transition_state(branch, "developing")

    # Ticket summary (only for logging/MR title)
    summary = state.get("summary") or issue_key
    multi_repo = len(repos) > 1
    api_mode = app_config["issue_tracker"]["api_mode"]

    results = _run_impl_fan_out(
        issue_key, branch, base_branch, summary, statuses,
        repos, api_mode, multi_repo,
    )

    # If blocked again during plan, _run_impl_fan_out already handled it.
    if any(r.get("blocked") for r in results):
        return True

    # Same post-implementation flow as the normal run.
    ok_repos = [r for r in results if r["success"]]
    err_repos = [r for r in results if not r["success"]]

    if ok_repos:
        lines = [f"Implementation complete for {issue_key}.", ""]
        for r in ok_repos:
            lines.append(f"- **{r['name']}**: {r['mrUrl']}")
        if err_repos:
            lines.append("")
            lines.append("Failed:")
            for r in err_repos:
                lines.append(f"- **{r['name']}**: {r['error']}")
        _try_add_comment(issue_key, "\n".join(lines))
        _try_notify_slack(
            f"MRs created for {issue_key}: " +
            ", ".join(r["mrUrl"] for r in ok_repos)
        )
        _try_transition_issue(issue_key, statuses["done"])
        transition_state(branch, "awaiting-review")
        logger.info(f"  RESUME COMPLETED: {issue_key} — {len(ok_repos)} MR(s), {len(err_repos)} failure(s)")
    else:
        error_summary = "; ".join(f"{r['name']}: {r['error']}" for r in err_repos) or "no MRs created"
        _try_add_comment(issue_key, f"Pipeline failed for {issue_key}. Errors: {error_summary}")
        _try_notify_slack(f"{issue_key} pipeline failed: {error_summary}")
        transition_state(branch, "failed", error={
            "phase": "developing", "agent": "pipeline",
            "message": error_summary,
        })
    return True


# ─── Rework Pipeline ───────────────────────────────────

def run_rework_phases(issue_key, branch, pr_id, statuses, repo_dir):
    """Drive the rework loop: parse feedback -> apply fixes -> push -> awaiting-review.

    Same feature branch as the original implementation. Python now handles
    the push; the rework agent commits locally only.

    Args:
        issue_key: Ticket key (e.g. "EV-14942").
        branch: Git branch name (same branch as original MR/PR).
        pr_id: PR/MR identifier.
        statuses: Dict of issue status names.
        repo_dir: Absolute path to the target repo directory.
    """
    state = get_state(branch)
    rework_num = (state.get("reworkCount", 0) if state else 0) + 1

    logger.info(f"\n{'='*60}")
    logger.info(f"  REWORK STARTED: {issue_key} (iteration {rework_num})")
    logger.info(f"  Branch: {branch}")
    logger.info(f"  PR/MR: {pr_id}")
    logger.info(f"{'='*60}\n")

    base_branch = get_base_branch()
    _log_step(issue_key, f"Checking out feature branch {branch}...")
    _prepare_repo_for_branch(repo_dir, base_branch, feature_branch=branch)

    if is_api_mode():
        _log_step(issue_key, f"Transitioning ticket to '{statuses['development']}'...")
        try:
            adapter, _ = get_issue_tracker()
            adapter.transition_issue(issue_key, statuses["development"])
        except Exception as e:
            transition_state(branch, "failed", error={
                "phase": "reworking", "agent": "pipeline",
                "message": f"Failed to transition ticket: {e}",
            })
            return

    transition_state(branch, "reworking")

    # ── Step 1: Parse feedback ───────────────────────────
    feedback_input = json.dumps({"issueKey": issue_key, "branch": branch, "prId": pr_id})
    result = _run_phase(
        issue_key, branch, "feedback-parser", "feedback-parser",
        feedback_input, statuses, repo_dir,
        phase_scope=FEEDBACK_PARSER_SCOPE,
    )
    if result is None:
        return

    # ── Step 2: Apply rework ─────────────────────────────
    rework_input = json.dumps({"issueKey": issue_key, "branch": branch})
    result = _run_phase(
        issue_key, branch, "rework", "phase:rework",
        rework_input, statuses, repo_dir,
        phase_scope=REWORK_SCOPE,
    )
    if result is None:
        return

    # ── Step 3: Python pushes ────────────────────────────
    _log_step(issue_key, f"Pushing rework commits on {branch}...")
    try:
        push_local_branch(repo_dir, branch)
    except Exception as e:
        transition_state(branch, "failed", error={
            "phase": "reworking", "agent": "pipeline",
            "message": f"git push failed: {e}",
        })
        return

    # ── Step 4: Complete — back to awaiting review ───────
    transition_state(branch, "awaiting-review")
    _try_transition_issue(issue_key, statuses["done"])
    _try_add_comment(issue_key, f"Rework iteration {rework_num} complete for {issue_key}.")
    _try_notify_slack(f"Rework complete for {issue_key} (iteration {rework_num})")

    logger.info(f"  REWORK COMPLETED: {issue_key} (iteration {rework_num})")
