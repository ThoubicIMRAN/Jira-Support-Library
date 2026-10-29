from pathlib import Path
import shutil
HERE = Path(__file__).resolve().parent
ROOT = next((p for p in (Path.cwd(), HERE.parent) if (p / "app.py").exists()), None)
if not ROOT:
    raise SystemExit("Run from app root")
for rel in [
    "database.py", "config.py", "app.py", "utils/navigation.py",
    "views/profile.py", "views/whats_new.py", "views/settings.py",
    "services/avatar_service.py", "scripts/migrate_avatar.py",
]:
    src = HERE / rel
    if src.is_file():
        (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, ROOT / rel)
        print("updated", rel)
print("Restart app. Avatar columns auto-patch on bootstrap; or run: python scripts/migrate_avatar.py")
