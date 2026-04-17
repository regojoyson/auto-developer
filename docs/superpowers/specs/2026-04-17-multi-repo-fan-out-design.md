# Multi-Repo Fan-Out Pipeline — Design

**Date:** 2026-04-17
**Status:** Design
**Builds on:** [2026-04-17-phase-boundary-redesign-design.md](./2026-04-17-phase-boundary-redesign-design.md)

## 1. Problem

A single Jira ticket may require code changes across 2–4 sub-repos under a `parentDir`-mode parent directory. Today the pipeline processes exactly one repo per ticket, forcing humans to split such tickets manually or skip automation entirely. Real example: a ticket "Add 2FA to user login" might need changes in `edgereg-modulith` (auth service), `badge-editor` (frontend), and `edgereg-report` (audit logging). The pipeline must analyze which repos are affected and produce one MR per repo.

## 2. Goals

- One Jira ticket → N MRs across N sub-repos (N = 1..4 typically), all linked back to the same ticket.
- Same feature-branch name reused across all N repos for simple mental model and routing.
- Rework scoped to the specific repo whose MR was commented on — untouched MRs stay untouched.
- Ticket only transitions to "Code Review" after ALL N MRs are created.
- Graceful fallback to single-repo flow when the picker determines only one repo is affected.

## 3. Non-goals

- Parallel execution across repos (sequential for now; parallelism is a later optimization).
- Monorepo-style single-MR-touching-multiple-dirs (doesn't apply — sub-repos are independent git repos).
- Cross-repo atomic merges.
- Different feature-branch names per repo.

## 4. Architecture

### 4.1 Flow overview

```
Webhook arrives (EV-14945, no component)
    ↓
Phase 0a — Repo Selection (picker agent)
    Reads ticket + list of git sub-repos + (optional) their READMEs
    Output: __PIPELINE_RESULT__:{"repos": ["modulith", "badge-editor"]}
    ↓
For each chosen repo (sequential):
    ↓
  Phase 1 — Analyze (analyze agent, ANALYZE_SCOPE)
    Writes TICKET.md in that repo's root
  Python creates remote branch, commits TICKET.md via git-provider API
    ↓
  Phase 2 — Plan (plan agent, PLAN_SCOPE)
    Writes PLAN.md focused on THIS repo's scope of the ticket
  Python commits PLAN.md
    ↓
  Phase 3 — Implement (implement agent, IMPLEMENT_SCOPE)
    Agent edits code + commits locally
  Python pushes + creates MR
    ↓
All repos complete
    ↓
Python transitions Jira ticket to "Code Review"
Python posts single summary comment listing all MR URLs
Pipeline state → "awaiting-review"
```

### 4.2 State model change

Current state (single repo):

```json
{
  "issueKey": "EV-14945",
  "branch": "ev-14945_xxx",
  "state": "developing",
  "repoPath": "/.../edgereg-modulith",
  "prId": 123
}
```

New state (multi-repo):

```json
{
  "issueKey": "EV-14945",
  "branch": "ev-14945_xxx",
  "state": "developing",
  "repos": [
    {
      "name": "edgereg-modulith",
      "path": "/.../edgereg-modulith",
      "state": "completed",
      "prId": 123,
      "mrUrl": "https://gitlab/.../merge_requests/123"
    },
    {
      "name": "badge-editor",
      "path": "/.../badge-editor",
      "state": "developing",
      "prId": null,
      "mrUrl": null
    }
  ]
}
```

**Backward compatibility:** keep `repoPath`, `prId`, `mrUrl` as convenience aliases at the top level, populated from `repos[0]` for single-repo tickets. Dashboard can keep using those for simple display, and power-users inspect `repos` for the full picture.

**Per-repo sub-state:** `repos[i].state` tracks each repo's progress independently: `pending` → `analyzing` → `planning` → `developing` → `completed` → (later) `reworking` → `completed`.

### 4.3 Picker agent — return a list

`agents/repo-picker.md` updated:

- Existing input unchanged.
- Output changed from `{"repo": "x"}` to `{"repos": ["x", "y"]}`.
- New rule in prompt: "pick as few repos as possible — if the ticket is cleanly one repo, return a one-element list. Do not over-include."

### 4.4 Pipeline fan-out

`run_pipeline_phases` loops over `state["repos"]`:

```python
for repo_entry in state["repos"]:
    repo_dir = repo_entry["path"]
    repo_name = repo_entry["name"]

    _prepare_repo_for_branch(repo_dir, base_branch)
    git_api = <create api scoped to this repo's origin>

    _update_repo_sub_state(branch, repo_name, "analyzing")
    analyze (writes TICKET.md in this repo's root)
    python commits TICKET.md via this repo's api

    _update_repo_sub_state(branch, repo_name, "planning")
    plan (writes PLAN.md in this repo's root)
    python commits PLAN.md

    _update_repo_sub_state(branch, repo_name, "developing")
    implement (agent writes code, commits locally)
    python pushes
    python creates MR
    record mrUrl + prId on the repo entry

    _update_repo_sub_state(branch, repo_name, "completed")

# After the loop
python transitions ticket to "Code Review"
python posts one summary comment listing all repos[*].mrUrl
transition_state(branch, "awaiting-review")
```

**Failure handling:** if one repo fails, pipeline continues with the remaining repos (best-effort), marks the failed repo with an `error` field, and reports per-repo status in the summary comment. Ticket still transitions to "Code Review" if at least one MR succeeded. If ALL fail, pipeline transitions to `failed`.

Rationale: partial success is valuable to reviewers. Better to have 2 of 3 MRs ready for review than to block the whole ticket on a flaky third repo.

### 4.5 Rework routing

Current rework flow: git-provider webhook arrives with `branch` + `pr_id` → `run_rework_phases(branch, pr_id)` → runs `feedback-parser` then `rework` on `state["repoPath"]`.

New rework flow:

1. Webhook arrives with `branch` + `pr_id` + (GitLab-specific) `project_id`.
2. Find the state record: `state = get_state(branch)`.
3. Find which repo entry owns this `pr_id`: `repo_entry = next(r for r in state["repos"] if r["prId"] == pr_id)`.
4. Run rework ONLY in `repo_entry["path"]`. Other repos in the ticket are untouched.
5. Update that repo entry's state: `completed` → `reworking` → `completed`.
6. Do NOT transition the Jira ticket (other MRs may still be awaiting review).

**Dashboard implication:** rework history is per-repo. A single ticket could have rework iteration 2 in `edgereg-modulith` while `badge-editor` is still on iteration 1.

### 4.6 Completion semantics

"Done" in the existing pipeline meant "MR created, transitioned to Code Review". Multi-repo version: "all selected repos have had MRs created (even if some failed), ticket transitions to Code Review, summary comment lists what landed and what didn't".

### 4.7 Webhook + state changes

`src/providers/git/gitlab.py::parse_webhook` already returns `pr_id`. It does NOT currently return `project_id`. Add that to the parsed dict so the rework handler can disambiguate when the same branch name exists across repos.

`src/state/manager.py`:

- Update `create_state` to accept a list of repos (or a single one, kept backward-compatible).
- New helper: `update_repo_sub_state(branch, repo_name, new_sub_state, **extra)` — updates one entry in `repos[]`.
- New helper: `find_repo_by_pr_id(state, pr_id)` — used by rework handler.

### 4.8 Phase labels

New `PHASE_NAMES` additions:

- `"phase:repo-picker"` = `"Phase 0 — Repo Selection"` (already added in a prior commit)
- `"phase:<repo_name>:analyze"`, `"phase:<repo_name>:plan"`, etc. — dynamically scoped labels so dashboard logs are clear which repo is currently running.

Simplest: prefix labels with `<repo_name>:` when in multi-repo mode. E.g. `"phase:edgereg-modulith:analyze"` → dashboard shows "Phase 1 — Analyze (edgereg-modulith)".

## 5. Files changed

**Modified:**

- `src/executor/pipeline.py` — new fan-out loop, per-repo git-api client, per-repo sub-state updates.
- `src/state/manager.py` — new repos[] schema, sub-state helpers, find-by-pr-id.
- `src/providers/git/gitlab.py` — webhook parser also returns `project_id`.
- `src/routes/git_provider.py` — rework handler looks up repo by prId before dispatching.
- `agents/repo-picker.md` — return list of repos, not single repo.
- `src/executor/phase_scope.py` — no change unless we split REPO_PICKER_SCOPE from per-repo ANALYZE/PLAN/IMPLEMENT (no change needed).

**No changes to:**

- `src/executor/pipeline_git.py` — helpers already take `api` + `repo_dir` params; reused as-is.
- `src/executor/runner.py`, `src/providers/cli/*` — agent invocation unchanged.
- `agents/analyze.md`, `plan.md`, `implement.md`, `rework.md` — each still writes to CWD, which the pipeline sets per-repo.

## 6. Migration

- Existing state files (single-repo schema) are read-compatible: state manager detects missing `repos[]` and synthesizes it from top-level `repoPath` / `prId`. All new states use the new schema.
- Existing in-flight tickets complete using their current state.

## 7. Open questions / risks

1. **GitLab webhook `project_id` availability** — verify the GitLab MR Hook payload includes `project.id`. (High confidence yes — it's a standard field.)
2. **Concurrent rework races** — if two reviewers comment on two different MRs at the same second, two rework threads spawn. They touch different repos, so no collision on files; but both read+write the same state JSON. Add a file-level lock around `repos[]` updates, or use atomic write (temp file + rename).
3. **Orphaned branches** — if Phase 3 fails on repo 2 of 3, repo 2's local feature branch exists but was never pushed. Best-effort cleanup: leave it; operator can prune stale branches periodically.
4. **Picker over-selection** — if the picker returns 4 repos but only 1 actually needed changes, the other 3 will produce empty PLANs or near-empty code changes. Mitigate via the new picker rule: "pick as few repos as possible". Acceptable failure mode: human ignores those MRs.
5. **Ticket rollback** — if the whole pipeline fails before any MR is created, transition ticket back to "Ready for Development" so it's visible in the backlog. Current code transitions to `failed` but doesn't touch the Jira status — consider whether to fix in this PR or later.

## 8. Testing

- Unit: state-manager tests for the new schema, `find_repo_by_pr_id`, backward-compat with single-repo records.
- Integration: existing e2e test (mocked CLI) needs to assert the fan-out — current test expects 3 agent invocations (analyze/plan/implement), new test expects `1 (picker) + N*3` invocations for N repos.
- Live smoke: one multi-repo ticket (EV-14945 or similar) through the full pipeline. Verify: N branches created, N MRs exist, each repo's MR description references the ticket, Jira shows N MR links in the summary comment.
