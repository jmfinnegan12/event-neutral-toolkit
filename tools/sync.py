"""Copy src/eventneutral.py into every skill. Skill installers copy only a skill's own folder."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "eventneutral.py"

for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
    target = skill.parent / "scripts" / "eventneutral.py"
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(SOURCE, target)
    print(target.relative_to(ROOT))
