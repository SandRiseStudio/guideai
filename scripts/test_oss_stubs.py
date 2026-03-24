#!/usr/bin/env python3
"""Test all OSS stubs work correctly without enterprise installed."""

import sys

print("Testing OSS stub imports...")
print()

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
        failed += 1


# Test 1: guideai.crypto
def test_crypto():
    from guideai.crypto import AuditSigner, SignatureMetadata, SigningError
    signer = AuditSigner()
    assert signer.is_loaded == False
    assert signer.can_sign == False
    meta = signer.sign_record(b"test")
    assert isinstance(meta, SignatureMetadata)
    assert signer.verify_record(b"test", None) == True
test("guideai.crypto - NoOp signer works", test_crypto)


# Test 2: guideai.crypto.signing backward compat
def test_crypto_signing():
    from guideai.crypto.signing import AuditSigner, load_signer_from_settings
    signer = load_signer_from_settings()
    assert signer.can_sign == False
test("guideai.crypto.signing - backward compat", test_crypto_signing)


# Test 3: guideai.analytics
def test_analytics():
    from guideai.analytics import TelemetryKPIProjector
    assert TelemetryKPIProjector is None
test("guideai.analytics - None stub", test_analytics)


# Test 4: guideai.analytics.warehouse
def test_analytics_warehouse():
    from guideai.analytics.warehouse import AnalyticsWarehouse
    assert AnalyticsWarehouse is None
test("guideai.analytics.warehouse - None stub", test_analytics_warehouse)


# Test 5: guideai.research
def test_research():
    from guideai.research import COMPREHENSION_SYSTEM_PROMPT, CodebaseAnalyzer
    assert COMPREHENSION_SYSTEM_PROMPT == ""
    assert CodebaseAnalyzer is None
test("guideai.research - stub works", test_research)


# Test 6: guideai.research.prompts
def test_research_prompts():
    from guideai.research.prompts import COMPREHENSION_SYSTEM_PROMPT
    assert COMPREHENSION_SYSTEM_PROMPT == ""
test("guideai.research.prompts - stub works", test_research_prompts)


# Test 7: guideai.research.ingesters
def test_research_ingesters():
    from guideai.research.ingesters import BaseIngester, MarkdownIngester
    assert BaseIngester is None
    assert MarkdownIngester is None
test("guideai.research.ingesters - None stubs", test_research_ingesters)


# Test 8: guideai.research.report
def test_research_report():
    from guideai.research.report import render_report
    try:
        render_report()
        raise AssertionError("should have raised ImportError")
    except ImportError:
        pass  # Expected
test("guideai.research.report - raises ImportError", test_research_report)


# Test 9: guideai.midnighter
def test_midnighter():
    from guideai.midnighter import create_midnighter_service
    try:
        create_midnighter_service()
        raise AssertionError("should have raised ImportError")
    except ImportError:
        pass  # Expected
test("guideai.midnighter - raises ImportError", test_midnighter)


# Test 10: guideai.billing
def test_billing():
    try:
        from guideai.billing import BillingService
        # BillingService is None since enterprise not installed
        # (or billing pkg itself may not be installed)
    except ImportError:
        pass  # standalone billing pkg not installed, that's OK
test("guideai.billing - loads without crash", test_billing)


# Test 11: Core import
def test_core():
    import guideai
test("import guideai - core import works", test_core)


print()
print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
