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


def _handle_blocked(issue_key, branch, statuses, result):
    """Handle an agent reporting the ticket is blocked."""
    reason = _extract_blocked_reason(result)
    _log_phase(issue_key, "phase:analyze", f"BLOCKED — {reason}")

    _try_add_comment(issue_key,
        f"Pipeline blocked — additional information needed:\n\n{reason}")
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

def _run_pipeline_for_repo(
    issue_key, branch, base_branch, summary, statuses,
    repo_name, repo_dir, ticket_data, api_mode,
) -> dict:
    """Run analyze → plan → implement → push → create MR for ONE repo.

    Updates per-repo sub-state in the shared state record via
    ``update_repo_sub_state``. Catches per-repo failures and returns a
    summary dict (does NOT transition the overall pipeline to "failed").

    Returns:
        Dict with keys:
            success: bool — all three phases + push + MR creation succeeded
            prId: int | None
            mrUrl: str | None
            error: str | None
    """
    from src.state.manager import update_repo_sub_state
    import os as _os

    try:
        # Prepare repo on base branch (fresh checkout)
        update_repo_sub_state(branch, repo_name, "preparing")
        _prepare_repo_for_branch(repo_dir, base_branch)

        # Build git-provider API client scoped to THIS repo
        git_adapter, _ = get_git_provider()
        git_api = git_adapter.create_api(dict(_os.environ), repo_dir=repo_dir)

        # Create the remote branch for this repo
        create_remote_branch(git_api, branch=branch, base=base_branch)

        # ── Phase 1 — Analyze ───────────────────────────
        update_repo_sub_state(branch, repo_name, "analyzing")
        analyze_payload = {
            "issueKey": issue_key,
            "branch": branch,
            "summary": summary,
            "baseBranch": base_branch,
            "statuses": statuses,
            "apiMode": api_mode,
            "repo": repo_name,  # hint to the agent that this is one of N
        }
        if ticket_data:
            analyze_payload["ticketData"] = ticket_data
        result = _run_repo_phase(
            issue_key, branch, "analyze",
            f"phase:{repo_name}:analyze",
            json.dumps(analyze_payload), statuses, repo_dir,
            phase_scope=ANALYZE_SCOPE,
        )
        if result is None:
            raise RuntimeError("analyze phase failed or blocked")

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
        result = _run_repo_phase(
            issue_key, branch, "plan",
            f"phase:{repo_name}:plan",
            plan_input, statuses, repo_dir,
            phase_scope=PLAN_SCOPE,
        )
        if result is None:
            raise RuntimeError("plan phase failed or blocked")

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
        return {"success": True, "prId": pr_id, "mrUrl": mr_url, "error": None}

    except Exception as e:
        err = str(e)
        _log_step(issue_key, f"[{repo_name}] failed: {err}")
        update_repo_sub_state(branch, repo_name, "failed", error=err)
        return {"success": False, "prId": None, "mrUrl": None, "error": err}


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

    # ── Transition ticket to Development (once) ─────────
    if is_api_mode():
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
                "phase": "analyzing",
                "agent": "pipeline",
                "message": f"Failed to transition ticket to '{statuses['development']}': {error_msg}",
            })
            _try_notify_slack(f"{issue_key} pipeline failed — could not transition ticket")
            return
    else:
        _log_step(issue_key, "Ticket transition will be handled by agent via MCP")

    # ── Fan out: one full pipeline per chosen repo ──────
    api_mode = app_config["issue_tracker"]["api_mode"]
    current_state = get_state(branch)
    repos = (current_state.get("repos") if current_state else None) or []
    _log_step(issue_key, f"Fanning out across {len(repos)} repo(s): {[r['name'] for r in repos]}")

    # Branch-level state is coarse — flip it ONCE at the start of the fan-out.
    # Per-repo granular state lives in state.repos[i].state.
    if current_state and current_state.get("state") == "analyzing":
        transition_state(branch, "planning")
        transition_state(branch, "developing")

    results = []
    for repo_entry in repos:
        repo_name = repo_entry["name"]
        repo_dir_i = repo_entry["path"]

        result = _run_pipeline_for_repo(
            issue_key, branch, base_branch, summary, statuses,
            repo_name, repo_dir_i, ticket_data, api_mode,
        )
        results.append({"name": repo_name, **result})

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
