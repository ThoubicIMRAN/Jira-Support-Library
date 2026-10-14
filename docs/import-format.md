# Project import / export format

Projects are imported from the project page (**Import from JSON**, admins only) and exported with **Export**.
The repository ships **no data**: create your projects in *Admin Settings → Content & users*, then import or add responses.

```json
{
  "schema_version": 1,
  "project": {"key": "KEY", "name": "Project name"},
  "categories": [
    {
      "name": "Category name",
      "responses": [
        {"title": "Response title", "badge": "LABEL", "preview": "Short summary",
         "response_body": "Hello @R,\n\nText of the response.\n\nBest regards,\n@NAME"}
      ]
    }
  ]
}
```

Limits: 2000 responses per import, title ≤ 200, badge ≤ 40, preview ≤ 300, body ≤ 20000 characters.
Placeholders: `@NAME @DESIGNATION @ROLE @R @DATE` and, with a loaded Jira ticket, `@TICKET @SUMMARY @ASSIGNEE @PROJECT @STATUS`.
