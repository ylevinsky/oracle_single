"""Unit tests for connection_store site aliases and path helpers."""

from __future__ import annotations

import unittest

import connection_store


class ConnectionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connections = {
            "RH": {"engine": "oracle", "host": "rh-oracle.example"},
            "HUN": {"engine": "oracle"},
            "local_rag": {"engine": "postgresql"},
        }

    def test_rh_aliases_resolve(self) -> None:
        for label in ("RH", "rh", "Repair Center", "repair-center"):
            with self.subTest(label=label):
                self.assertEqual(
                    connection_store.resolve_connection_name(label, self.connections),
                    "RH",
                )

    def test_unknown_connection_lists_oracle_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "Saved Oracle connections"):
            connection_store.resolve_connection_name("missing", self.connections)

    def test_oracle_site_index_skips_postgres(self) -> None:
        rows = connection_store.oracle_site_index(self.connections)
        names = {row["connection_name"] for row in rows}
        self.assertEqual(names, {"HUN", "RH"})
        rh = next(row for row in rows if row["connection_name"] == "RH")
        self.assertIn("repair center", rh["aliases"])


if __name__ == "__main__":
    unittest.main()