# Multi-Repo Fan-Out Implementation Plan

> **For agentic workers:** Execute task-by-task. Steps use checkbox (`- [ ]`) syntax. Spec: [2026-04-17-multi-repo-fan-out-design.md](../specs/2026-04-17-multi-repo-fan-out-design.md).

**Goal:** Fan out a single Jira ticket across 1–4 chosen sub-repos. Each repo gets its own branch, TICKET.md, PLAN.md, code changes, and MR. Ticket transitions to "Code Review" after all MRs are created. Rework is scoped to the commented MR's repo only.

**Architecture:** Picker agent returns a LIST of repos. Pipeline loops over them sequentially, running analyze → plan → implement → push → MR for each. State model gains a `repos[]` array; rework handler routes by `pr_id` → repo lookup.

---

## Task 1: Update picker agent to return a list of repos

**Files:**
- Modify: `agents/repo-picker.md`

- [ ] Update the "Steps" section to instruct the agent to pick 1..N repos (not exactly one).
- [ ] Change the output schema to `{"repos": ["name1", "name2"]}` (list, even for single-repo cases).
- [ ] Add rule: "pick as FEW repos as possible — one if it's cleanly one repo. Only include additional repos when the ticket genuinely spans them."
- [ ] Commit with: `feat(agents): repo-picker returns list of repos (multi-repo)`

---

## Task 2: Extend state schema with `repos[]` array

**Files:**
- Modify: `src/state/manager.py`

- [ ] Update `create_state(branch, issue_key, repo_path=None, repos=None)` — accept either the old single `repo_path` or a new `repos` list of `{"name", "path"}`. Persist both for backward compat (top-level `repoPath` stays as a convenience view of `repos[0]`).
- [ ] State record schema gains `"repos": [{"name", "path", "state": "pending", "prId": null, "mrUrl": null, "error": null}, ...]`.
- [ ] New helper: `update_repo_sub_state(branch, repo_name, new_sub_state, **extra)` — updates a single entry's sub-state and optional fields (prId, mrUrl, error). Atomic write (temp file + rename).
- [ ] New helper: `find_repo_by_pr_id(state, pr_id)` — returns the matching dict or None.
- [ ] Keep `update_state_repo_path(branch, repo_path)` working — also updates `repos[0]` when present.
- [ ] Commit: `feat(state): add repos[] array schema for multi-repo tickets`

---

## Task 3: Parser returns `project_id`; add rework lookup

**Files:**
- Modify: `src/providers/git/gitlab.py`
- Modify: `src/routes/git_provider.py`

- [ ] In `GitLabAdapter.parse_webhook`, add `"project_id": payload.get("project", {}).get("id")` to the returned dict (for both MR Hook and Note Hook events).
- [ ] In `src/routes/git_provider.py` `event == "comment"` branch, after resolving the state, use the new `find_repo_by_pr_id(state, pr_id)` helper. If it returns a repo entry, set `repo_dir = repo_entry["path"]`. If not, fall back to `state.get("repoPath", ".")` (backward compat).
- [ ] Pass `repo_dir` to `run_rework_phases(...)` as before — it's already a parameter.
- [ ] For `event == "approved"`, if the state has a `repos[]`, only transition to "merged" when ALL MRs are approved (store approval bitmask in `repos[i].approved`). For now: approve any single MR = transition to "merged" to preserve existing behavior. Can be tightened later.
- [ ] Commit: `feat(routes/git): rework routes to the commented MR's repo only`

---

## Task 4: Pipeline fan-out loop

**Files:**
- Modify: `src/executor/pipeline.py`

This is the biggest change. Broken into sub-steps.

- [ ] Update the picker-invocation block to parse `{"repos": [...]}` (list) and fall back to `{"repo": "x"}` (string) for backward compat with any old caller. Produce a list of repo entries `[{"name", "path"}]`.
- [ ] Persist the list into state via `create_state` (or `update_state` if the state already exists — webhook already called `create_state`, so we may need to augment).
- [ ] Wrap the existing Phase 1 + Phase 2 + Phase 3 + Step 7 block in a `for repo_entry in repos:` loop. Inside the loop:
    - Set `repo_dir = repo_entry["path"]`, `repo_name = repo_entry["name"]`.
    - Call `_prepare_repo_for_branch(repo_dir, base_branch)`.
    - Obtain `git_api = git_adapter.create_api(env, repo_dir=repo_dir)`.
    - Update sub-state to `"analyzing"` before Phase 1, `"planning"` before Phase 2, `"developing"` before Phase 3, `"completed"` after MR is created. Record `prId` and `mrUrl` in the sub-state.
    - On any per-repo failure: record `error` on the sub-state, continue to the next repo (best-effort).
    - Label phases as `phase:<repo_name>:analyze` etc. so dashboard disambiguates.
- [ ] After the loop: collect successful + failed repos. Post one summary comment listing each repo + its MR URL (or error). Transition ticket to `statuses["done"]` if at least one succeeded; to `statuses["blocked"]` or keep in progress if all failed.
- [ ] If only ONE repo was chosen by picker, the loop still runs — this single-repo case becomes just N=1 fan-out. No special-casing needed.
- [ ] Commit: `feat(pipeline): fan out phases across multiple picked repos`

---

## Task 5: Live smoke test

- [ ] Re-trigger EV-14945 (or any component-less ticket).
- [ ] Expected log flow: "Phase 0 — Repo Selection" → picker output shows `repos: [...]` → for each chosen repo: "Phase 1 — Analyze (repo_name)" → ... → "Phase 3 — Implement (repo_name)" → "pushed" → "MR created: <url>".
- [ ] Verify N distinct branches on GitLab (one per picked repo).
- [ ] Verify N distinct MRs on GitLab, each linked to the ticket key in the title.
- [ ] Verify Jira comment lists all MR URLs.
- [ ] Post-test cleanup: if anything went wrong, `delete_state_by_issue_key('EV-14945')` to reset.

---

## Known deferrals (out of scope for this plan)

- Parallel fan-out across repos (sequential for now).
- Approval-count-aware transition to "merged" (approve one = merged for now).
- `repos[i].reworkCount` per-repo (the existing top-level `reworkCount` is used; fine for now).
- Dashboard UI updates to show per-repo sub-states (dashboard reads the new schema; visual polish can follow).
