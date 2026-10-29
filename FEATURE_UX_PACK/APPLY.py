from pathlib import Path
import shutil
HERE = Path(__file__).resolve().parent
ROOT = next((p for p in (Path.cwd(), HERE.parent) if (p / "app.py").exists()), None)
if not ROOT:
    raise SystemExit("Run from app root")
for rel in [
    "database.py",
    "services/avatar_service.py",
    "services/account_service.py",
    "services/jira_service.py",
    "views/profile.py",
    "views/admin_panel.py",
    "views/jira_action_dialog.py",
    "views/my_dashboard.py",
    "utils/navigation.py",
    "app.py",
    "scripts/migrate_avatar.py",
    "FEATURE_UX_PACK.md",
]:
    src = HERE / rel
    if src.is_file():
        (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, ROOT / rel)
        print("updated", rel)
print("Then: python scripts/migrate_avatar.py && restart app")
print("Sidebar: My Dashboard — requires Jira connected for the user")
