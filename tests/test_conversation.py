"""Conversation memory unit tests (Phase 12).

Uses a temporary DB so the test never pollutes the real `db/graph.db`. Each
test gets a fresh schema via `_make_kg(tmp_path)`.
"""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from capabilities.graph_store import GraphStore
from core.knowledge_graph import KnowledgeGraph


def _make_kg(tmp_path: Path) -> KnowledgeGraph:
    kg = KnowledgeGraph(
        db_path=tmp_path / "test.db",
        vector_dir=tmp_path / "chroma",  # Chroma init still runs but tests don't use it
    )
    # Bypass Chroma init for speed — only the SQLite side matters here
    kg.graph.init_schema()
    kg._initialized = True
    return kg


class ConversationFacadeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.kg = _make_kg(self.tmp_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    def test_get_or_create_creates_when_missing(self) -> None:
        conv = self.kg.get_or_create_conversation(chat_id="c1", channel="telegram")
        self.assertIsNotNone(conv["id"])
        self.assertEqual(conv["chat_id"], "c1")
        self.assertEqual(conv["channel"], "telegram")
        self.assertTrue(conv["active"])

    def test_get_or_create_reuses_active(self) -> None:
        conv1 = self.kg.get_or_create_conversation(chat_id="c2", channel="telegram")
        conv2 = self.kg.get_or_create_conversation(chat_id="c2", channel="telegram")
        self.assertEqual(conv1["id"], conv2["id"])

    def test_channel_separation(self) -> None:
        conv_tg = self.kg.get_or_create_conversation(chat_id="same", channel="telegram")
        conv_tui = self.kg.get_or_create_conversation(chat_id="same", channel="tui")
        self.assertNotEqual(conv_tg["id"], conv_tui["id"])

    def test_reset_then_new(self) -> None:
        conv1 = self.kg.get_or_create_conversation(chat_id="c3", channel="telegram")
        n = self.kg.reset_conversation(chat_id="c3", channel="telegram")
        self.assertEqual(n, 1)
        conv2 = self.kg.get_or_create_conversation(chat_id="c3", channel="telegram")
        self.assertNotEqual(conv1["id"], conv2["id"])

    def test_chat_id_str_cast(self) -> None:
        # Passing int should normalize to str (Telegram chat_id is int).
        self.kg.get_or_create_conversation(chat_id=42, channel="telegram")
        # Same as string should return same row
        conv = self.kg.get_or_create_conversation(chat_id="42", channel="telegram")
        # Two get_or_create with int + str should reuse, not create twice
        with self.kg.graph.conn() as c:
            count = c.execute(
                "SELECT COUNT(*) AS n FROM conversations WHERE chat_id = '42'"
            ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_append_increments_ordinal(self) -> None:
        conv = self.kg.get_or_create_conversation(chat_id="c4", channel="telegram")
        self.kg.append_conversation_message(
            conversation_id=conv["id"], role="user", content="hi")
        self.kg.append_conversation_message(
            conversation_id=conv["id"], role="assistant", content="hello")
        self.kg.append_conversation_message(
            conversation_id=conv["id"], role="user", content="bye")
        msgs = self.kg.recent_messages(conv["id"], limit=10)
        self.assertEqual([m["ordinal"] for m in msgs], [0, 1, 2])
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])

    def test_recent_messages_returns_chronological(self) -> None:
        conv = self.kg.get_or_create_conversation(chat_id="c5", channel="telegram")
        for i in range(10):
            self.kg.append_conversation_message(
                conversation_id=conv["id"],
                role="user" if i % 2 == 0 else "assistant",
                content=f"m{i}",
            )
        msgs = self.kg.recent_messages(conv["id"], limit=4)
        # Last 4 in oldest→newest order
        self.assertEqual([m["content"] for m in msgs], ["m6", "m7", "m8", "m9"])

    def test_idle_timeout_creates_new(self) -> None:
        conv1 = self.kg.get_or_create_conversation(chat_id="c6", channel="telegram")
        # Backdate last_active to be older than 6h cutoff
        old = (datetime.now() - timedelta(hours=7)).isoformat()
        with self.kg.graph.conn() as c:
            c.execute(
                "UPDATE conversations SET last_active_at = ? WHERE id = ?",
                (old, conv1["id"]),
            )
        conv2 = self.kg.get_or_create_conversation(chat_id="c6", channel="telegram")
        self.assertNotEqual(conv1["id"], conv2["id"])

    def test_unknown_sender_works_without_person_id(self) -> None:
        # person_id=None should be allowed
        conv = self.kg.get_or_create_conversation(
            chat_id="anon", channel="telegram", person_id=None,
        )
        self.assertIsNone(conv["person_id"])
        self.kg.append_conversation_message(
            conversation_id=conv["id"], role="user", content="who am i?")
        msgs = self.kg.recent_messages(conv["id"])
        self.assertEqual(len(msgs), 1)


if __name__ == "__main__":
    unittest.main()
