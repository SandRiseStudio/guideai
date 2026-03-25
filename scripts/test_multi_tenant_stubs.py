"""Test OSS multi_tenant stubs import correctly."""
import sys
import traceback

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  [PASS] {name}")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()
        failed += 1

print("Testing multi_tenant hybrid split imports...\n")

# OSS sub-modules should import cleanly with full functionality
def test_context():
    from guideai.multi_tenant.context import TenantContext, TenantMiddleware, get_current_org_id
    assert TenantContext is not None, "TenantContext should exist"
    assert TenantMiddleware is not None, "TenantMiddleware should exist"
test("context - TenantContext/TenantMiddleware", test_context)

def test_contracts():
    from guideai.multi_tenant.contracts import (
        Organization, Project, MemberRole, ProjectRole,
        CreateOrgRequest, OrgPlan, OrgStatus, ProjectVisibility,
    )
    assert Organization is not None
    assert MemberRole is not None
test("contracts - Organization/Project/MemberRole", test_contracts)

def test_board_contracts():
    from guideai.multi_tenant.board_contracts import (
        WorkItemStatus, WorkItemType, WorkItemPriority,
        CreateWorkItemRequest, Board, BoardColumn,
    )
    assert WorkItemStatus is not None
    assert Board is not None
test("board_contracts - WorkItem/Board types", test_board_contracts)

def test_permissions():
    from guideai.multi_tenant.permissions import (
        PermissionService, OrgPermission, ProjectPermission,
        PermissionDenied, NotAMember,
    )
    assert PermissionService is not None
    assert OrgPermission is not None
test("permissions - PermissionService/OrgPermission", test_permissions)

# Enterprise stubs should import without error, returning None or no-op
def test_org_service_stub():
    from guideai.multi_tenant.organization_service import OrganizationService
    # Without guideai-enterprise, should be None
    assert OrganizationService is None, f"Expected None, got {OrganizationService}"
test("organization_service stub - None fallback", test_org_service_stub)

def test_invitation_service_stub():
    from guideai.multi_tenant.invitation_service import InvitationService
    assert InvitationService is None, f"Expected None, got {InvitationService}"
test("invitation_service stub - None fallback", test_invitation_service_stub)

def test_settings_stub():
    from guideai.multi_tenant.settings import (
        SettingsService, OrgSettings, ProjectSettings,
        BrandingSettings, NotificationSettings,
    )
    assert SettingsService is None
    assert OrgSettings is None
    assert BrandingSettings is None
test("settings stub - None fallback", test_settings_stub)

def test_api_stub():
    from guideai.multi_tenant.api import create_org_routes
    assert callable(create_org_routes), "Should be callable"
    try:
        create_org_routes()
        assert False, "Should raise ImportError"
    except ImportError:
        pass  # Expected
test("api stub - raises ImportError", test_api_stub)

def test_settings_api_stub():
    from guideai.multi_tenant.settings_api import create_settings_routes
    assert callable(create_settings_routes), "Should be callable"
    try:
        create_settings_routes()
        assert False, "Should raise ImportError"
    except ImportError:
        pass  # Expected
test("settings_api stub - raises ImportError", test_settings_api_stub)

# Full package import should work
def test_package_import():
    from guideai.multi_tenant import (
        TenantContext, TenantMiddleware,
        OrganizationService, InvitationService,
        PermissionService, OrgPermission,
        SettingsService, OrgSettings,
        create_org_routes, create_settings_routes,
    )
    assert TenantContext is not None, "OSS TenantContext should exist"
    assert PermissionService is not None, "OSS PermissionService should exist"
    assert OrganizationService is None, "Enterprise OrganizationService should be None"
    assert InvitationService is None, "Enterprise InvitationService should be None"
    assert SettingsService is None, "Enterprise SettingsService should be None"
test("package import - hybrid works", test_package_import)

# Core guideai should still import
def test_guideai_core():
    import guideai
    assert guideai is not None
test("guideai core import", test_guideai_core)

print(f"\nResults: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
