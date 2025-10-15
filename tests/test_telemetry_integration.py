"""Telemetry integration tests covering ActionService and AgentAuth instrumentation."""

from __future__ import annotations

import unittest

from guideai.action_contracts import ActionCreateRequest, Actor, ReplayRequest
from guideai.action_service import ActionService
from guideai.agent_auth import AgentAuthClient, EnsureGrantRequest, GrantDecision
from guideai.telemetry import InMemoryTelemetrySink, TelemetryClient


class TelemetryIntegrationTests(unittest.TestCase):
    def test_action_service_emits_record_and_replay_events(self) -> None:
        sink = InMemoryTelemetrySink()
        telemetry = TelemetryClient(sink=sink)
        service = ActionService(telemetry=telemetry)

        actor = Actor(id="strategist-1", role="STRATEGIST", surface="CLI")
        request = ActionCreateRequest(
            artifact_path="docs/sample.md",
            summary="Sample action",
            behaviors_cited=["behavior_update_docs_after_changes"],
            metadata={"commands": ["guideai record-action"]},
        )
        created = service.create_action(request, actor)

        replay_request = ReplayRequest(action_ids=[created.action_id])
        service.replay_actions(replay_request, actor)

        event_types = [event.event_type for event in sink.events]
        self.assertIn("action_recorded", event_types)
        self.assertIn("action_replay_start", event_types)
        self.assertIn("action_replay_complete", event_types)

        recorded_events = [event for event in sink.events if event.event_type == "action_recorded"]
        self.assertTrue(recorded_events)
        self.assertEqual(recorded_events[0].payload["artifact_path"], request.artifact_path)
        self.assertEqual(recorded_events[0].actor["surface"], "cli")

    def test_agent_auth_emits_decision_events(self) -> None:
        sink = InMemoryTelemetrySink()
        telemetry = TelemetryClient(sink=sink)
        client = AgentAuthClient(telemetry=telemetry)

        request = EnsureGrantRequest(
            agent_id="agent-cli",
            user_id="user-123",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
        )
        response = client.ensure_grant(request)
        self.assertEqual(response.decision, GrantDecision.ALLOW)

        decision_events = [event for event in sink.events if event.event_type == "auth_grant_decision"]
        self.assertTrue(decision_events)
        self.assertEqual(decision_events[0].payload["decision"], GrantDecision.ALLOW.value)
        self.assertEqual(decision_events[0].payload["agent_id"], request.agent_id)
        self.assertEqual(decision_events[0].actor["surface"], "cli")


if __name__ == "__main__":
    unittest.main()
