#!/usr/bin/env python3
"""Debug script to test deprecate behavior."""

import sys
import psycopg2
from guideai.behavior_service import BehaviorService
from guideai.storage.postgres_pool import PostgresPool
from guideai.telemetry import NoOpTelemetryClient
from guideai.models import CreateBehaviorRequest, Actor, DeprecateBehaviorRequest

# Get connection details from environment
import os
host = os.getenv("GUIDEAI_PG_HOST_BEHAVIOR", "localhost")
port = int(os.getenv("GUIDEAI_PG_PORT_BEHAVIOR", "6433"))
user = os.getenv("GUIDEAI_PG_USER_BEHAVIOR", "postgres")
password = os.getenv("GUIDEAI_PG_PASSWORD_BEHAVIOR", "postgres")
database = os.getenv("GUIDEAI_PG_DB_BEHAVIOR", "guideai_behavior")

# Create a direct psycopg2 connection to query the database
def get_direct_connection():
    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database
    )

# Initialize service
pool = PostgresPool(
    service_name="behavior",
    pg_dsn=f"postgresql://{user}:{password}@{host}:{port}/{database}",
    max_conn=5,
    connect_timeout=5,
)
service = BehaviorService(pool, telemetry=NoOpTelemetryClient())
actor = Actor(id="debug-user", role="ADMIN", surface="DEBUG")

print("Creating test behavior...")
create_req = CreateBehaviorRequest(
    name="debug_test_behavior",
    description="Test deprecate",
    instruction="Test instructions",
    role_focus="STRATEGIST",
    trigger_keywords=[],
    examples=[],
)
behavior = service.create_behavior(create_req, actor)
behavior_id = behavior.behavior_id
version = behavior.version
print(f"Created behavior: {behavior_id} v{version}, status={behavior.status}")

# Check status directly
conn = get_direct_connection()
cur = conn.cursor()
cur.execute("SELECT status FROM behavior_versions WHERE behavior_id = %s AND version = %s", (behavior_id, version))
direct_status = cur.fetchone()[0]
print(f"Direct query after create: status={direct_status}")
cur.close()
conn.close()

print("\nDeprecating behavior...")
deprecate_req = DeprecateBehaviorRequest(
    behavior_id=behavior_id,
    version=version,
    effective_to="2025-01-01T00:00:00Z",
    successor_behavior_id=None,
)
deprecated = service.deprecate_behavior(deprecate_req, actor)
print(f"Deprecate returned: status={deprecated.status}")

# Check status directly
conn = get_direct_connection()
cur = conn.cursor()
cur.execute("SELECT status FROM behavior_versions WHERE behavior_id = %s AND version = %s", (behavior_id, version))
direct_status = cur.fetchone()[0]
print(f"Direct query after deprecate: status={direct_status}")
cur.close()
conn.close()

# Check via service
fetched = service._fetch_behavior_version(behavior_id, version)
print(f"Service fetch after deprecate: status={fetched.status}")

print("\nCleanup...")
cur = conn.cursor()
cur.execute("DELETE FROM behavior_versions WHERE behavior_id = %s", (behavior_id,))
cur.execute("DELETE FROM behaviors WHERE behavior_id = %s", (behavior_id,))
conn.commit()
cur.close()
conn.close()

print("Done!")
