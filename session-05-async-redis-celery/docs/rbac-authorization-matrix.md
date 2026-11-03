# RBAC Authorization Matrix

Who can do what in TaskFlow, and where each rule is enforced. Every rule below is
enforced server-side and covered by `tests/auth/`.

## Roles

| Role | Scope | Stored as | In one line |
| --- | --- | --- | --- |
| Admin | Global, every project | `user.role = "admin"` | Full control of users, projects, tasks and imports |
| Manager | Global role + per project | `user.role = "manager"`, and `project_member.member_role = "manager"` per project | Creates projects and runs the projects they manage (one manager can manage many) |
| Member | Per project | `user.role = "member"` (every signup), `project_member.member_role = "member"` | Reads their projects, creates tasks for themselves, moves only their own tasks |

- The global `manager` role allows creating projects and being assigned to projects
  by an admin. What a user can do **inside a project** comes only from their
  `project_member` row, so a manager of project A has no rights on project B.
- Demoting a manager to member (`PATCH /users/{id}/role`) turns their project
  `manager` memberships into `member` ones.
- Both role columns are guarded by CHECK constraints (migration `c4a7e2f19b3d`).

## Matrix

"Their projects" = projects where the user has a `project_member` row.
"Own task" = the task is assigned to them.

| Area | Action | Endpoint | Admin | Manager | Member |
| --- | --- | --- | --- | --- | --- |
| Auth | Sign up (always `member`) | `POST /auth/signup` | Public | Public | Public |
| Auth | Log in, get a JWT | `POST /auth/login` | Public | Public | Public |
| Auth | Own profile | `GET /auth/me` | Yes | Yes | Yes |
| Users | Create a user with a role | `POST /users` | Yes | No | No |
| Users | List / view users | `GET /users`, `GET /users/{id}` | All | People in their projects | People in their projects |
| Users | Change a user's global role | `PATCH /users/{id}/role` | Yes (not their own) | No | No |
| Projects | Create a project | `POST /projects` | Yes, optionally for a manager (`owner_id`) | Yes, becomes its manager | No |
| Projects | List / view projects | `GET /projects`, `GET /projects/{id}` | All | Their projects | Their projects |
| Projects | Assign a manager to an existing project | `POST /projects/{id}/managers` | Yes | No | No |
| Projects | List members | `GET /projects/{id}/members` | Yes | Their projects | Their projects |
| Projects | Add a member | `POST /projects/{id}/members` | Yes | Their projects | No |
| Projects | Remove a member / a manager | `DELETE /projects/{id}/members/{user_id}` | Yes / Yes | Their projects / No | No |
| Tasks | Create a task | `POST /tasks` | Yes | Their projects | Their projects, assigned to themselves |
| Tasks | List / view tasks | `GET /tasks`, `GET /tasks/{id}` | All | Their projects | Their projects |
| Tasks | Assign or reassign | `POST /tasks/{id}/assign` | Yes | Their projects | No |
| Tasks | Change status | `PATCH /tasks/{id}/status` | Yes | Their projects | Own task only |
| Tasks | Cancel a task | `PATCH /tasks/{id}/status` | Yes | Their projects | No |
| Tasks | History, activity, notifications | `GET /tasks/{id}/history`, `/activity`, `/notifications` | All | Their projects | Their projects |
| Imports | Run / list raw imports | `POST`, `GET /imports/tasks/raw` | Yes | No | No |

Task assignees must belong to the task's project (`422 ASSIGNEE_NOT_IN_PROJECT`).
The assigner recorded in the audit trail is always the authenticated caller.

## Error responses

All errors use `{"detail": {"error": {"code": ..., "message": ...}}}`.

| Case | Status | Code |
| --- | --- | --- |
| Missing, invalid or expired token, or the token's user no longer exists | `401` | `UNAUTHORIZED` (+ `WWW-Authenticate: Bearer`) |
| Wrong username/email or password at login | `401` | `INVALID_CREDENTIALS` |
| Outside the project (not a member, not admin) | `404` | `PROJECT_NOT_FOUND` / `TASK_NOT_FOUND` / `USER_NOT_FOUND` |
| In the project, but the role does not allow the action | `403` | `FORBIDDEN`, or `STATUS_CHANGE_FORBIDDEN` for status changes |

Outsiders get `404` rather than `403` so the API does not reveal which projects
and tasks exist. Checks run in this order: token, project membership, role rule,
then the status workflow (`409`).

## Where it is enforced

| Layer | What | Where |
| --- | --- | --- |
| Authentication | Decode the JWT, reload the user from the DB (the token's `role` claim is never trusted) | `app/auth/dependencies.py` → `get_current_user`, attached with `APIRouter(dependencies=...)` on the users, projects, tasks and imports routers |
| Global role | `require_roles(...)`, `require_admin` | Route dependencies (`POST /users`, `PATCH /users/{id}/role`, `POST /projects`, `POST /projects/{id}/managers`, imports router) |
| Project role and ownership | `require_project_access`, `require_project_manager` | `app/auth/permissions.py`, called from the services |
| Safety net | Every non-public route must declare bearer security and return 401 without a token | `tests/auth/test_route_protection.py` |

Security is attached with dependencies rather than middleware. Most rules need the
project or task being acted on, which only the service layer has, and dependencies
keep FastAPI's error handling and OpenAPI security docs working.

## Tokens and passwords

- Access token only (no refresh token), HS256 via PyJWT, lifetime
  `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30). Claims: `sub` (user id), `role`,
  `type="access"`, `iat`, `exp`.
- Login: OAuth2 password form at `POST /auth/login`; `username` accepts a username
  or an email, so Swagger's Authorize button works.
- Passwords are hashed with Argon2 (`pwdlib`). Unknown logins run a dummy hash check
  so they take as long as wrong passwords. Accounts hashed with the old SHA-256
  scheme can no longer log in and need a new password.
- The first admin comes from `make create-admin`; signup can never create one.
