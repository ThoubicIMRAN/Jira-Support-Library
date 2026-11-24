# Error catalogue (JSL-*)

User-facing errors should use codes from `utils/errors.py` (`ERROR_CATALOGUE`).

| Code         | Severity | Message (summary)             | When to use                       |
| ------------ | -------- | ----------------------------- | --------------------------------- |
| JSL-AUTH-001 | error    | Sign-in failed                | Bad credentials                   |
| JSL-AUTH-002 | warning  | Session expired or revoked    | Cookie/session invalid            |
| JSL-AUTH-003 | error    | Account inactive              | Disabled user                     |
| JSL-PERM-001 | error    | Permission denied             | RBAC failure                      |
| JSL-JIRA-001 | error    | Jira not connected            | Missing config/credentials        |
| JSL-JIRA-002 | error    | Jira request failed           | API/transport errors              |
| JSL-JIRA-003 | error    | Issue not found / not allowed | Key or project prefix             |
| JSL-JIRA-004 | error    | Could not update issue        | Transition/comment/attach failure |
| JSL-DATA-001 | error    | Invalid input                 | Validation                        |
| JSL-FILE-001 | error    | Unsupported or invalid file   | Attachments                       |
| JSL-DB-001   | critical | Database error                | Persistence failures              |
| JSL-SYS-001  | critical | Unexpected application error  | Unhandled exceptions              |
| JSL-RATE-001 | warning  | Too many attempts             | Rate limit                        |

## Rules

1. Never show raw stack traces to normal users.
2. Always log unexpected errors with a short reference id.
3. Prefer domain exceptions (`ValueError`, `JiraError`, `RateLimitExceeded`) that already carry safe text; map to catalogue codes when adding new UI paths.
4. Do not log secrets, tokens, or passwords.

## API

```python
from utils.errors import safe_message, format_error, user_error, lookup_error

st.error(safe_message(exc))  # exception path
st.error(user_error("JSL-PERM-001"))  # explicit code
st.error(format_error("JSL-SYS-001", ref=cid))  # with correlation id
```
