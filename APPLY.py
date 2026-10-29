from pathlib import Path
import shutil
HERE = Path(__file__).resolve().parent
ROOT = next((p for p in (Path.cwd(), HERE.parent) if (p / "app.py").exists()), None)
if not ROOT:
    raise SystemExit("Run from app root")
shutil.copy2(HERE/"services"/"template_fields.py", ROOT/"services"/"template_fields.py")
shutil.copy2(HERE/"views"/"jira_action_dialog.py", ROOT/"views"/"jira_action_dialog.py")
print("OK: hyperlink-aware template fields")
