"""Execution event hub for real-time run updates over WebSocket."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Set

from starlette.websockets import WebSocket


class ExecutionEventHub:
    """In-memory pub/sub for execution updates."""

    def __init__(self) -> None:
        self._run_subscribers: Dict[str, Set[WebSocket]] = {}
        self._project_subscribers: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        *,
        run_id: Optional[str] = None,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            if run_id:
                self._run_subscribers.setdefault(run_id, set()).add(websocket)
            if org_id and project_id:
                key = f"{org_id}:{project_id}"
                self._project_subscribers.setdefault(key, set()).add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for subscribers in list(self._run_subscribers.values()):
                subscribers.discard(websocket)
            for subscribers in list(self._project_subscribers.values()):
                subscribers.discard(websocket)

    def publish_status(self, payload: Dict[str, Any]) -> None:
        self._schedule_broadcast("execution.status", payload)

    def publish_step(self, payload: Dict[str, Any]) -> None:
        self._schedule_broadcast("execution.step", payload)

    def _schedule_broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._broadcast(event_type, payload))

    async def _broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        run_id = payload.get("run_id")
        org_id = payload.get("org_id")
        project_id = payload.get("project_id")
        targets: Set[WebSocket] = set()

        async with self._lock:
            if run_id and run_id in self._run_subscribers:
                targets.update(self._run_subscribers[run_id])
            if org_id and project_id:
                key = f"{org_id}:{project_id}"
                targets.update(self._project_subscribers.get(key, set()))

        if not targets:
            return

        message = {"type": event_type, "payload": payload}
        for websocket in list(targets):
            try:
                await websocket.send_json(message)
            except Exception:
                await self.disconnect(websocket)
