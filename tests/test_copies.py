"""Each skill ships its own copy of the tool, because skill installers copy only the skill's folder."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Copies(unittest.TestCase):
    def test_every_skill_has_a_current_copy(self):
        source = (ROOT / "src" / "eventneutral.py").read_bytes()
        skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(skills), 4)
        for skill in skills:
            copy = skill.parent / "scripts" / "eventneutral.py"
            self.assertTrue(copy.exists(), f"{copy} is missing; run python tools/sync.py")
            self.assertEqual(copy.read_bytes(), source, f"{copy} is out of date; run python tools/sync.py")


if __name__ == "__main__":
    unittest.main()
