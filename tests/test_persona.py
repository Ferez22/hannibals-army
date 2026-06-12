"""Persona store + SCRIBE unit tests (Phase 12).

Persona files go to a temporary dir to avoid touching `memory/persona/`.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import config


class PersonaStoreTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._orig_dir = config.PERSONA_DIR
        config.PERSONA_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        config.PERSONA_DIR = self._orig_dir
        self._tmp.cleanup()

    def test_round_trip(self) -> None:
        from capabilities import persona_store
        data = {
            "identity": {"name": "Test", "role": "CTO", "tier": "c_level"},
            "working_on": [{"project": "P1", "role": "lead"}],
            "colleagues_close": [{"name": "A", "relation": "peer"}],
            "communication_style": [],
            "preferences": [],
            "notes": "",
        }
        persona_store.save_persona("pid_42", data)
        loaded = persona_store.load_persona("pid_42")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["identity"]["name"], "Test")
        self.assertEqual(loaded["_meta"]["updated_by"], "SCRIBE")

    def test_missing_returns_none(self) -> None:
        from capabilities import persona_store
        self.assertIsNone(persona_store.load_persona("nope"))

    def test_corrupt_returns_none(self) -> None:
        from capabilities import persona_store
        path = persona_store.persona_path("corrupt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("::: this is not valid yaml: -[")
        self.assertIsNone(persona_store.load_persona("corrupt"))

    def test_caps_applied(self) -> None:
        from capabilities import persona_store
        data = {"working_on": [{"project": f"p{i}"} for i in range(20)]}
        persona_store.save_persona("pid_caps", data)
        loaded = persona_store.load_persona("pid_caps")
        self.assertLessEqual(
            len(loaded["working_on"]),
            persona_store.SECTION_CAPS["working_on"],
        )

    def test_atomic_write_no_tmp_left(self) -> None:
        from capabilities import persona_store
        persona_store.save_persona("pid_atomic", {"identity": {"name": "x"}})
        # No leftover .tmp files
        leftovers = list(config.PERSONA_DIR.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_render_empty_returns_empty_string(self) -> None:
        from capabilities import persona_store
        # None and empty dict are both treated as "no persona" — no block injected
        self.assertEqual(persona_store.render_persona_for_prompt(None), "")
        self.assertEqual(persona_store.render_persona_for_prompt({}), "")

    def test_render_contains_name_and_sections(self) -> None:
        from capabilities import persona_store
        data = {
            "identity": {"name": "Alice", "role": "CEO", "tier": "ceo"},
            "working_on": [{"project": "Phoenix", "role": "owner"}],
            "colleagues_close": [{"name": "Bob", "relation": "direct report"}],
        }
        rendered = persona_store.render_persona_for_prompt(data)
        self.assertIn("Alice", rendered)
        self.assertIn("CEO", rendered)
        self.assertIn("Phoenix", rendered)
        self.assertIn("Bob", rendered)

    def test_list_personas(self) -> None:
        from capabilities import persona_store
        persona_store.save_persona("p1", {"identity": {"name": "A"}})
        persona_store.save_persona("p2", {"identity": {"name": "B"}})
        ids = persona_store.list_personas()
        self.assertEqual(sorted(ids), ["p1", "p2"])

    def test_delete(self) -> None:
        from capabilities import persona_store
        persona_store.save_persona("p3", {"identity": {"name": "X"}})
        self.assertTrue(persona_store.delete_persona("p3"))
        self.assertFalse(persona_store.delete_persona("p3"))


if __name__ == "__main__":
    unittest.main()
