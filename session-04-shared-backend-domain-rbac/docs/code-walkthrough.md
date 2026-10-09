# Code Walkthrough — Task Status Workflow

Notes on how the status workflow is wired together and, more importantly, why each
piece looks the way it does. Written so I can walk through the PR without re-deriving
everything from scratch.

## The path one status change takes

```
PATCH /tasks/{id}/status
   ↓
route          parse request, resolve the acting user, call service, serialize reply
   ↓
service        404? 403? no-op? 409? then write
   ↓
workflow       is this move allowed at all?
   ↓
repository/DB  stage the rows, flush, one commit
```

Each layer only answers its own question. The route doesn't know the rules, the
workflow doesn't know HTTP, the repository doesn't make decisions.

---

## 1. The rulebook: `app/workflows/task_status_workflow.py`

Everything else refers to this file, so I started here.

The whole rule set is one dictionary:

```python
TRANSITIONS = {
    TODO:        {IN_PROGRESS},
    IN_PROGRESS: {IN_REVIEW},
    IN_REVIEW:   {DONE},
    DONE:        set(),
    CANCELLED:   set(),
}
```

Key = where the task is now, value = where it's allowed to go next. Reading it as
sentences: "if the task is TODO, the only legal next status is IN_PROGRESS."

Why a dict and not a chain of `if` statements:

- the whole rulebook fits in five lines, so it's readable at a glance
- adding a rule later is one line, not another branch
- checking a move is `target in set`, which is O(1)

Terminal states (`DONE`, `CANCELLED`) are just empty sets. No extra flag, no special
case — "nowhere to go" is expressed by having no exits.

I used `frozenset` instead of `set` because the rulebook should never be mutated at
runtime. Nobody can accidentally add a rule while the app is running.

The four helpers (`allowed_next`, `is_terminal`, `can_transition`, `validate`) are
deliberately tiny. `can_transition` answers yes/no; `validate` is the one that raises
when the answer is no. Two functions, one decision point, no duplicated logic.

They're classmethods because there's nothing to instantiate. There's no per-request
workflow state, so a single shared rulebook attached to the class is the honest shape.

One detail I had to decide: `current == target` returns `False` from
`can_transition`. Moving a task to the status it already has isn't a transition, it's
a no-op. The service handles the no-op case before the workflow is ever asked, so this
doesn't cause problems, and it keeps the workflow honest about what "transition"
means.

---

## 2. Why the workflow raises a plain exception, not an HTTP error

The workflow raises `InvalidTransitionError`, which is just an `Exception` subclass
carrying three fields: `current`, `target`, `allowed`. The service then translates it:

```python
try:
    TaskStatusWorkflow.validate(prev_status, target_status)
except InvalidTransitionError as exc:
    raise InvalidStatusTransitionError(...) from exc    # ← this one is a 409
```

Reasons I kept them separate:

- **The workflow shouldn't depend on FastAPI.** If it raised HTTPException it would
  need to import fastapi, and then the rulebook can only ever live inside a web app.
  Right now the same file runs fine in a script or a background job — the demo script
  calls it directly.
- **The same fact may need different presentations.** An API wants 409 + JSON. A
  worker job would want a log line. A CLI would want exit code 1. The workflow should
  produce the fact and let whoever is holding it decide the format.
- **Structured fields beat a formatted string.** The domain error carries typed
  values (`current`, `target`, `allowed`). The HTTP error carries a pre-built message
  string meant for the wire. Facts are more useful than prose if a caller wants to
  build something different.
- **One file owns the error envelope.** All response bodies share the same
  `{"error": {code, message}}` shape, and it all comes from `core/exceptions.py`.
  If the workflow built responses, that knowledge would be spread into the domain.
- **`raise ... from exc` keeps the chain**, so logs show the HTTP error *and* the
  domain error that caused it.

Why 409 specifically: the request itself is valid and the target is a real status
value, so 400/422 would be blaming the payload. The conflict is between the task's
current state and the requested state — that's what 409 CONFLICT means.

Quick test story: the workflow tests just call `pytest.raises(InvalidTransitionError)`
around a plain function. No client, no database, ~1ms per test.

---

## 3. The service: `TaskService.update_task_status`

This is the middle manager. It sequences the checks and owns the transaction.

Order of operations, and the reason each step sits where it does:

1. **Retrieve the task → 404.** Nothing else is meaningful without it.
2. **Authorize → 403.** Before validation on purpose: an unauthorized caller
   shouldn't be able to learn which transitions exist by reading 409 vs 403.
3. **Map API values to model values.** API says `in_progress`, the DB enum says
   `IN_PROGRESS`. Translated once, here, so everything downstream sees one spelling.
4. **Same status → early return.** Retrying the current status is a no-op: return 200,
   write nothing. The audit trail shouldn't record "nothing happened".
5. **`TaskStatusWorkflow.validate` → 409.** Last gate before any write, so an invalid
   move fails with zero rows touched. No cleanup needed because nothing was written.
6. **The transaction block.**
7. **Refresh and return** the persisted row.

The authorization helper (`_ensure_can_change_status`) is an allow-list with the deny
at the end:

```python
if actor.role == "ADMIN":                    return
if task.assigned_to == actor.id:             return
if project.owner_id == actor.id:             return
if member_role in {"OWNER", "MANAGER"}:      return
raise StatusChangeForbiddenError()           # everyone else lands here
```

Fail-closed: a new caller isn't allowed by accident, they have to match one of the
four rules explicitly. It maps one-to-one onto the Session 4 suggested rules
(members only for their own tasks, managers/owners/admins as the escalation paths).

The transaction block, which I kept in the Session 3 style:

```python
try:
    stage status update     # queued in the session, no SQL sent yet
    stage history
    stage activity
    await db.flush()        # sends the SQL, still inside the transaction
    await db.commit()       # one commit for all three
except Exception:
    await db.rollback()
    raise
```

Three words matter here:

- **stage** = queued, not sent. All three records are built before any of them reach
  the server.
- **flush** = send the SQL but keep the transaction open. This forces DB-level errors
  (foreign key, not-null) to happen here, inside the `try`, so they roll back too.
  Without it some failures only show up at commit time.
- **commit** = called exactly once. One transaction, one commit, three records
  durable together.

If anything fails at any point, `rollback` undoes all three. The board, the history
and the activity can never disagree — that's the "no partial state" requirement.

The `raise` inside `except` matters too: rollback must not swallow the error, the API
still needs to return a real failure to the caller.

## What the service deliberately does not do

- doesn't know which transitions are legal (that's the workflow)
- doesn't parse requests or build JSON (that's the route)
- doesn't write SQL (that's the repository)

Which is the whole separation argument in one function.

---

## The other files, short version

**`app/core/exceptions.py`** — added four errors, all following the pattern that was
already in the file: an HTTPException subclass with a baked status code and the shared
`{"error": {code, message}}` body. 409 for the transition conflict, 401 for missing /
unknown identity, 403 for the RBAC denial. One choice worth remembering: an unknown
user in the header is 401, not 404 — it's credential validation, not a resource
lookup.

**`app/api/dependencies/deps.py`** — `get_current_user` reads `X-User-ID`, looks the
user up, raises 401 if either is missing. This is a placeholder for real JWT auth
later; the contract (401 with those codes) stays the same when it's swapped out.

**`app/api/v1/routes/tasks.py`** — the endpoint is intentionally five lines: call the
service, map to DTO. There's a unit test that greps this file for workflow identifiers
and asserts the function body has no `if`/`raise`/`try`, so nobody accidentally moves
rules into the route later.

**`app/repositories/project_repository.py`** — added `get_member_role`, a single
SELECT of the member role for a user in a project. The service needs it for the
OWNER/MANAGER check; repositories only answer queries, they never decide.

**`app/schemas/task.py`** — added `in_review` to `TaskStatusValue`. It existed in the
database enum from Session 1 but was missing from the API enum, so the workflow
couldn't actually be walked end to end over HTTP before this.

---

## Questions I expect during review

**Why is the same error defined twice?** Because they live in different layers. The
workflow's exception is a domain fact, the service's is an HTTP response. The `from exc`
links them.

**Why not validate before checking permissions?** Because that would tell an
unauthorized caller which transitions exist.

**What happens if the process dies between flush and commit?** Postgres rolls the
transaction back on its own — an open transaction is never durable. The explicit
rollback in the service handles every case where we're still alive.

**Why is the same-status request a 200 and not a 409?** It's not an invalid
transition, it's no transition. Clients retrying should get a success with the
unchanged state, and the audit trail should stay clean.

**Is the header secure?** No, and it isn't meant to be — it's a stand-in until JWT
auth lands in Task 5. That's on the open questions list in the demo doc.

