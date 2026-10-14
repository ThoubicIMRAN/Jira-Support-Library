import re
from datetime import date

# Placeholders filled from the signed-in user
_USER_KEYS = ('NAME', 'DESIGNATION', 'ROLE', 'R', 'DATE')
# Placeholders filled from the loaded Jira ticket (left untouched when no ticket is loaded)
TICKET_KEYS = ('TICKET', 'SUMMARY', 'ASSIGNEE', 'PROJECT', 'STATUS')
PLACEHOLDER_HELP = '@NAME @DESIGNATION @ROLE @R @DATE · ticket: @TICKET @SUMMARY @ASSIGNEE @PROJECT @STATUS'
_PATTERN = re.compile(
    r'@(' + '|'.join(sorted(_USER_KEYS + TICKET_KEYS, key=len, reverse=True)) + r')\b', re.I
)


def personalize(text, user, project_id, designation_overrides=None, recipient='Customer', context=None):
    """Replace @NAME, @DESIGNATION, @ROLE, @R, @DATE and (when ``context`` is given)
    @TICKET, @SUMMARY, @ASSIGNEE, @PROJECT, @STATUS placeholders.

    Ticket placeholders with no value stay as written so the agent notices them.
    """
    overrides = designation_overrides or {}
    designation = (
        overrides.get(project_id)
        or getattr(user, 'designation', None)
        or 'Support Engineer'
    ).strip()
    values = {
        'NAME': getattr(user, 'full_name', None) or getattr(user, 'username', 'User'),
        'DESIGNATION': designation,
        'ROLE': getattr(user, 'role', 'user'),
        'R': recipient or 'Customer',
        'DATE': date.today().isoformat(),
    }
    for key in TICKET_KEYS:
        value = (context or {}).get(key)
        if value:
            values[key] = str(value)

    def _fill(match):
        return values.get(match.group(1).upper(), match.group(0))

    return _PATTERN.sub(_fill, text or '')


def unresolved_placeholders(text):
    """Ticket placeholders still present (e.g. no ticket loaded yet)."""
    found = {m.group(1).upper() for m in _PATTERN.finditer(text or '')}
    return sorted(found & set(TICKET_KEYS))
