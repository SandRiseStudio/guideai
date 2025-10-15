"""Parity tests ensuring ActionService stubs behave consistently across surfaces."""

from __future__ import annotations

import unittest

from guideai.action_service import ActionService
from guideai.adapters import (
    CLIActionServiceAdapter,
    MCPActionServiceAdapter,
    RestActionServiceAdapter,
)


class ActionServiceParityTests(unittest.TestCase):
    def setUp(self) -> None:
        service = ActionService()
        self.cli = CLIActionServiceAdapter(service)
        self.rest = RestActionServiceAdapter(service)
        self.mcp = MCPActionServiceAdapter(service)
        self.actor_id = "user-strategist"
        self.actor_role = "STRATEGIST"

    def _create_action_via_cli(self, suffix: str) -> dict:
        return self.cli.record_action(
            artifact_path=f"docs/sample-{suffix}.md",
            summary=f"Sample action {suffix}",
            behaviors_cited=["behavior_wire_cli_to_orchestrator"],
            metadata={"commands": ["guideai record-action"]},
            actor_id=self.actor_id,
            actor_role=self.actor_role,
        )

    def test_get_action_parity_across_surfaces(self) -> None:
        created = self._create_action_via_cli("one")
        action_id = created["action_id"]

        rest_record = self.rest.get_action(action_id)
        mcp_record = self.mcp.get(action_id)

        self.assertDictEqual(rest_record, created)
        self.assertDictEqual(mcp_record, created)

    def test_list_actions_consistent_ordering(self) -> None:
        created_ids = [self._create_action_via_cli(str(index))["action_id"] for index in range(3)]

        cli_list = self.cli.list_actions()
        rest_list = self.rest.list_actions()
        mcp_list = self.mcp.list()

        self.assertEqual([item["action_id"] for item in cli_list], created_ids)
        self.assertEqual(cli_list, rest_list)
        self.assertEqual(cli_list, mcp_list)

    def test_replay_updates_action_status(self) -> None:
        action_ids = [self._create_action_via_cli(str(index))["action_id"] for index in range(2)]

        replay_payload = {
            "action_ids": action_ids,
            "actor": {"id": self.actor_id, "role": self.actor_role},
            "strategy": "SEQUENTIAL",
            "options": {"skip_existing": False, "dry_run": False},
        }
        replay_result = self.rest.replay_actions(replay_payload)

        self.assertEqual(replay_result["status"], "SUCCEEDED")
        self.assertAlmostEqual(replay_result["progress"], 1.0)
        self.assertFalse(replay_result["failed_action_ids"])

        for action_id in action_ids:
            action = self.cli.get_action(action_id)
            self.assertEqual(action["replay_status"], "SUCCEEDED")

    def test_checksum_auto_calculation(self) -> None:
        action = self.cli.record_action(
            artifact_path="docs/capability_matrix.md",
            summary="Document capability matrix",
            behaviors_cited=["behavior_update_docs_after_changes"],
            metadata={},
            actor_id=self.actor_id,
            actor_role=self.actor_role,
        )
        self.assertTrue(action["checksum"])


if __name__ == "__main__":
    unittest.main()
