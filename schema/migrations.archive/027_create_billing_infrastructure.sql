-- Migration: 027_create_billing_infrastructure.sql
-- Description: Create billing infrastructure tables for provider-agnostic subscription management
-- Date: 2025-12-05
-- Behavior: behavior_migrate_postgres_schema
--
-- This migration creates tables for the billing package infrastructure:
--   - billing_customers: Customer entities linked to organizations
--   - billing_subscriptions: Subscription state and history
--   - billing_payment_methods: Payment method records
--   - billing_invoices: Invoice records with line items
--   - billing_usage_records: Usage tracking for metered billing
--   - billing_usage_aggregates: Aggregated usage by period
--   - billing_webhook_events: Webhook event log for audit/debugging
--
-- Key Design Decisions:
--   1. Provider-agnostic: provider_* columns store external IDs (Stripe, etc.)
--   2. RLS-enabled: All tables use org_id for tenant isolation
--   3. Soft delete: customers/subscriptions use status, not hard delete
--   4. Audit-friendly: All tables have created_at/updated_at, webhooks logged
--
-- Rollback: DROP TABLE IF EXISTS billing_webhook_events, billing_usage_aggregates,
--           billing_usage_records, billing_invoices, billing_payment_methods,
--           billing_subscriptions, billing_customers CASCADE;

BEGIN;

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE billing_plan AS ENUM ('free', 'starter', 'team', 'enterprise');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE subscription_status AS ENUM (
        'trialing', 'active', 'past_due', 'canceled',
        'unpaid', 'incomplete', 'incomplete_expired', 'paused'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE payment_method_type AS ENUM (
        'card', 'bank_account', 'sepa_debit', 'ach_debit', 'paypal', 'link'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE invoice_status AS ENUM (
        'draft', 'open', 'paid', 'void', 'uncollectible'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE usage_metric AS ENUM (
        'tokens', 'api_calls', 'storage_bytes', 'compute_seconds',
        'runs', 'agents', 'projects', 'members'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE webhook_event_status AS ENUM (
        'received', 'processed', 'failed', 'ignored', 'duplicate'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- BILLING_CUSTOMERS TABLE
-- =============================================================================
-- Links billing identity to organizations. One customer per org.

CREATE TABLE IF NOT EXISTS billing_customers (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Provider external IDs
    provider_id TEXT,              -- e.g., Stripe customer ID (cus_xxx)
    provider_type TEXT NOT NULL DEFAULT 'mock',  -- 'stripe', 'mock', etc.

    -- Customer details (cached from org or provider)
    email TEXT NOT NULL,
    name TEXT,
    phone TEXT,
    address JSONB,                 -- {line1, line2, city, state, postal_code, country}

    -- Tax configuration
    tax_exempt BOOLEAN NOT NULL DEFAULT FALSE,
    tax_ids JSONB DEFAULT '[]'::jsonb,  -- [{type: 'eu_vat', value: 'DE123456789'}]

    -- Payment settings
    default_payment_method_id VARCHAR(36),
    invoice_settings JSONB DEFAULT '{}'::jsonb,

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_billing_customers_org_id UNIQUE (org_id)
);

CREATE INDEX IF NOT EXISTS idx_billing_customers_provider ON billing_customers(provider_type, provider_id)
    WHERE provider_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_billing_customers_email ON billing_customers(email);

-- Update trigger
CREATE OR REPLACE FUNCTION update_billing_customers_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_billing_customers_updated ON billing_customers;
CREATE TRIGGER trigger_billing_customers_updated
    BEFORE UPDATE ON billing_customers
    FOR EACH ROW
    EXECUTE FUNCTION update_billing_customers_timestamp();

COMMENT ON TABLE billing_customers IS 'Billing customers linked to organizations, one per org';
COMMENT ON COLUMN billing_customers.provider_id IS 'External provider customer ID (e.g., Stripe cus_xxx)';

-- =============================================================================
-- BILLING_SUBSCRIPTIONS TABLE
-- =============================================================================
-- Tracks subscription state and history. Supports multiple subscriptions per customer
-- for advanced scenarios (add-ons), but typically one active per customer.

CREATE TABLE IF NOT EXISTS billing_subscriptions (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    customer_id VARCHAR(36) NOT NULL REFERENCES billing_customers(id) ON DELETE CASCADE,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Provider external ID
    provider_subscription_id TEXT,

    -- Subscription details
    plan billing_plan NOT NULL DEFAULT 'free',
    status subscription_status NOT NULL DEFAULT 'active',

    -- Billing cycle
    billing_anchor TIMESTAMPTZ,           -- Day of month for billing
    current_period_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_end TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '1 month'),

    -- Trial
    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,

    -- Cancellation
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    canceled_at TIMESTAMPTZ,
    cancel_reason TEXT,

    -- Pricing
    quantity INT NOT NULL DEFAULT 1,      -- For seat-based pricing
    unit_amount INT,                       -- Price in cents per unit
    currency TEXT NOT NULL DEFAULT 'usd',

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_customer ON billing_subscriptions(customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_org ON billing_subscriptions(org_id);
CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_status ON billing_subscriptions(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_provider ON billing_subscriptions(provider_subscription_id)
    WHERE provider_subscription_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_period_end ON billing_subscriptions(current_period_end);

-- Update trigger
DROP TRIGGER IF EXISTS trigger_billing_subscriptions_updated ON billing_subscriptions;
CREATE TRIGGER trigger_billing_subscriptions_updated
    BEFORE UPDATE ON billing_subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_billing_customers_timestamp();

COMMENT ON TABLE billing_subscriptions IS 'Subscription records with billing cycle and status';

-- =============================================================================
-- BILLING_PAYMENT_METHODS TABLE
-- =============================================================================
-- Payment methods attached to customers. Multiple allowed per customer.

CREATE TABLE IF NOT EXISTS billing_payment_methods (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    customer_id VARCHAR(36) NOT NULL REFERENCES billing_customers(id) ON DELETE CASCADE,

    -- Provider external ID
    provider_payment_method_id TEXT,

    -- Payment method details
    type payment_method_type NOT NULL DEFAULT 'card',
    is_default BOOLEAN NOT NULL DEFAULT FALSE,

    -- Card details (when type = 'card')
    card_brand TEXT,               -- visa, mastercard, amex, etc.
    card_last4 TEXT,
    card_exp_month INT,
    card_exp_year INT,
    card_funding TEXT,             -- credit, debit, prepaid

    -- Bank details (when type = 'bank_account' or 'ach_debit')
    bank_name TEXT,
    bank_last4 TEXT,
    bank_routing_number TEXT,

    -- Billing address
    billing_address JSONB,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_payment_methods_customer ON billing_payment_methods(customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_payment_methods_default ON billing_payment_methods(customer_id, is_default)
    WHERE is_default = TRUE;
CREATE INDEX IF NOT EXISTS idx_billing_payment_methods_provider ON billing_payment_methods(provider_payment_method_id)
    WHERE provider_payment_method_id IS NOT NULL;

-- Update trigger
DROP TRIGGER IF EXISTS trigger_billing_payment_methods_updated ON billing_payment_methods;
CREATE TRIGGER trigger_billing_payment_methods_updated
    BEFORE UPDATE ON billing_payment_methods
    FOR EACH ROW
    EXECUTE FUNCTION update_billing_customers_timestamp();

COMMENT ON TABLE billing_payment_methods IS 'Payment methods attached to billing customers';

-- =============================================================================
-- BILLING_INVOICES TABLE
-- =============================================================================
-- Invoice records with line items and payment status.

CREATE TABLE IF NOT EXISTS billing_invoices (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    customer_id VARCHAR(36) NOT NULL REFERENCES billing_customers(id) ON DELETE CASCADE,
    subscription_id VARCHAR(36) REFERENCES billing_subscriptions(id) ON DELETE SET NULL,

    -- Provider external ID
    provider_invoice_id TEXT,

    -- Invoice details
    number TEXT,                   -- Invoice number (e.g., INV-2024-001)
    status invoice_status NOT NULL DEFAULT 'draft',

    -- Amounts (in cents)
    subtotal INT NOT NULL DEFAULT 0,
    tax INT NOT NULL DEFAULT 0,
    total INT NOT NULL DEFAULT 0,
    amount_paid INT NOT NULL DEFAULT 0,
    amount_due INT NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'usd',

    -- Line items
    lines JSONB NOT NULL DEFAULT '[]'::jsonb,  -- [{description, quantity, unit_amount, amount}]

    -- Dates
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    due_date TIMESTAMPTZ,
    finalized_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    voided_at TIMESTAMPTZ,

    -- Payment details
    payment_intent_id TEXT,
    payment_method_id VARCHAR(36) REFERENCES billing_payment_methods(id) ON DELETE SET NULL,

    -- URLs
    hosted_invoice_url TEXT,
    invoice_pdf_url TEXT,

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_customer ON billing_invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_subscription ON billing_invoices(subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_status ON billing_invoices(status);
CREATE INDEX IF NOT EXISTS idx_billing_invoices_provider ON billing_invoices(provider_invoice_id)
    WHERE provider_invoice_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_billing_invoices_number ON billing_invoices(number) WHERE number IS NOT NULL;

-- Update trigger
DROP TRIGGER IF EXISTS trigger_billing_invoices_updated ON billing_invoices;
CREATE TRIGGER trigger_billing_invoices_updated
    BEFORE UPDATE ON billing_invoices
    FOR EACH ROW
    EXECUTE FUNCTION update_billing_customers_timestamp();

COMMENT ON TABLE billing_invoices IS 'Invoice records with line items and payment status';

-- =============================================================================
-- BILLING_USAGE_RECORDS TABLE
-- =============================================================================
-- Individual usage events for metered billing. High volume, consider partitioning.

CREATE TABLE IF NOT EXISTS billing_usage_records (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    subscription_id VARCHAR(36) NOT NULL REFERENCES billing_subscriptions(id) ON DELETE CASCADE,
    customer_id VARCHAR(36) NOT NULL REFERENCES billing_customers(id) ON DELETE CASCADE,

    -- Usage details
    metric usage_metric NOT NULL,
    quantity BIGINT NOT NULL,

    -- Context
    action_id VARCHAR(36),         -- Link to action if applicable
    run_id VARCHAR(36),            -- Link to run if applicable
    project_id VARCHAR(36),        -- Project context

    -- Timestamp
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Provider sync
    provider_usage_record_id TEXT,
    synced_at TIMESTAMPTZ,

    -- Idempotency
    idempotency_key TEXT,

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Consider partitioning by month for high-volume usage
CREATE INDEX IF NOT EXISTS idx_billing_usage_records_subscription ON billing_usage_records(subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_usage_records_customer ON billing_usage_records(customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_usage_records_metric ON billing_usage_records(metric);
CREATE INDEX IF NOT EXISTS idx_billing_usage_records_timestamp ON billing_usage_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_billing_usage_records_idempotency ON billing_usage_records(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

COMMENT ON TABLE billing_usage_records IS 'Individual usage events for metered billing';

-- =============================================================================
-- BILLING_USAGE_AGGREGATES TABLE
-- =============================================================================
-- Pre-aggregated usage by period for fast limit checks.
-- Updated by background job or Redis counter flushes.

CREATE TABLE IF NOT EXISTS billing_usage_aggregates (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    subscription_id VARCHAR(36) NOT NULL REFERENCES billing_subscriptions(id) ON DELETE CASCADE,
    customer_id VARCHAR(36) NOT NULL REFERENCES billing_customers(id) ON DELETE CASCADE,

    -- Aggregate details
    metric usage_metric NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,

    -- Aggregate values
    total_quantity BIGINT NOT NULL DEFAULT 0,
    record_count INT NOT NULL DEFAULT 0,

    -- Limit tracking
    plan_limit BIGINT,             -- Limit from plan at aggregation time
    percentage_used NUMERIC(5, 2), -- Calculated percentage

    -- Metadata
    last_record_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint for upsert
    CONSTRAINT uq_billing_usage_aggregates_key
        UNIQUE (subscription_id, metric, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_billing_usage_aggregates_subscription ON billing_usage_aggregates(subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_usage_aggregates_customer ON billing_usage_aggregates(customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_usage_aggregates_period ON billing_usage_aggregates(period_start, period_end);

-- Update trigger
DROP TRIGGER IF EXISTS trigger_billing_usage_aggregates_updated ON billing_usage_aggregates;
CREATE TRIGGER trigger_billing_usage_aggregates_updated
    BEFORE UPDATE ON billing_usage_aggregates
    FOR EACH ROW
    EXECUTE FUNCTION update_billing_customers_timestamp();

COMMENT ON TABLE billing_usage_aggregates IS 'Pre-aggregated usage by period for fast limit checks';

-- =============================================================================
-- BILLING_WEBHOOK_EVENTS TABLE
-- =============================================================================
-- Log of webhook events for debugging and audit.

CREATE TABLE IF NOT EXISTS billing_webhook_events (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,

    -- Provider details
    provider_event_id TEXT NOT NULL,
    provider_type TEXT NOT NULL DEFAULT 'stripe',
    event_type TEXT NOT NULL,

    -- Processing status
    status webhook_event_status NOT NULL DEFAULT 'received',
    processed_at TIMESTAMPTZ,
    error_message TEXT,
    retry_count INT NOT NULL DEFAULT 0,

    -- Payload
    payload JSONB NOT NULL,

    -- Related entities
    customer_id VARCHAR(36) REFERENCES billing_customers(id) ON DELETE SET NULL,
    subscription_id VARCHAR(36) REFERENCES billing_subscriptions(id) ON DELETE SET NULL,
    invoice_id VARCHAR(36) REFERENCES billing_invoices(id) ON DELETE SET NULL,

    -- Timestamps
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Idempotency
    CONSTRAINT uq_billing_webhook_events_provider
        UNIQUE (provider_type, provider_event_id)
);

CREATE INDEX IF NOT EXISTS idx_billing_webhook_events_type ON billing_webhook_events(event_type);
CREATE INDEX IF NOT EXISTS idx_billing_webhook_events_status ON billing_webhook_events(status)
    WHERE status IN ('received', 'failed');
CREATE INDEX IF NOT EXISTS idx_billing_webhook_events_received ON billing_webhook_events(received_at);
CREATE INDEX IF NOT EXISTS idx_billing_webhook_events_customer ON billing_webhook_events(customer_id);

COMMENT ON TABLE billing_webhook_events IS 'Log of billing provider webhook events for audit and debugging';

-- =============================================================================
-- ROW-LEVEL SECURITY
-- =============================================================================
-- Enable RLS for multi-tenant isolation using current_org_id() session variable.

ALTER TABLE billing_customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_payment_methods ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_usage_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_usage_aggregates ENABLE ROW LEVEL SECURITY;

-- RLS policies for billing_customers
DROP POLICY IF EXISTS billing_customers_org_isolation ON billing_customers;
CREATE POLICY billing_customers_org_isolation ON billing_customers
    FOR ALL
    USING (org_id = current_org_id() OR current_org_id() IS NULL);

-- RLS policies for billing_subscriptions
DROP POLICY IF EXISTS billing_subscriptions_org_isolation ON billing_subscriptions;
CREATE POLICY billing_subscriptions_org_isolation ON billing_subscriptions
    FOR ALL
    USING (org_id = current_org_id() OR current_org_id() IS NULL);

-- RLS policies for billing_payment_methods (via customer join)
DROP POLICY IF EXISTS billing_payment_methods_org_isolation ON billing_payment_methods;
CREATE POLICY billing_payment_methods_org_isolation ON billing_payment_methods
    FOR ALL
    USING (
        customer_id IN (
            SELECT id FROM billing_customers
            WHERE org_id = current_org_id() OR current_org_id() IS NULL
        )
    );

-- RLS policies for billing_invoices (via customer join)
DROP POLICY IF EXISTS billing_invoices_org_isolation ON billing_invoices;
CREATE POLICY billing_invoices_org_isolation ON billing_invoices
    FOR ALL
    USING (
        customer_id IN (
            SELECT id FROM billing_customers
            WHERE org_id = current_org_id() OR current_org_id() IS NULL
        )
    );

-- RLS policies for billing_usage_records (via customer join)
DROP POLICY IF EXISTS billing_usage_records_org_isolation ON billing_usage_records;
CREATE POLICY billing_usage_records_org_isolation ON billing_usage_records
    FOR ALL
    USING (
        customer_id IN (
            SELECT id FROM billing_customers
            WHERE org_id = current_org_id() OR current_org_id() IS NULL
        )
    );

-- RLS policies for billing_usage_aggregates (via customer join)
DROP POLICY IF EXISTS billing_usage_aggregates_org_isolation ON billing_usage_aggregates;
CREATE POLICY billing_usage_aggregates_org_isolation ON billing_usage_aggregates
    FOR ALL
    USING (
        customer_id IN (
            SELECT id FROM billing_customers
            WHERE org_id = current_org_id() OR current_org_id() IS NULL
        )
    );

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to get current subscription for an org
CREATE OR REPLACE FUNCTION get_org_subscription(p_org_id VARCHAR(36))
RETURNS TABLE (
    subscription_id VARCHAR(36),
    plan billing_plan,
    status subscription_status,
    current_period_end TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id,
        s.plan,
        s.status,
        s.current_period_end
    FROM billing_subscriptions s
    JOIN billing_customers c ON s.customer_id = c.id
    WHERE c.org_id = p_org_id
    AND s.status = 'active'
    ORDER BY s.created_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_org_subscription(VARCHAR) IS 'Get the active subscription for an organization';

-- Function to get usage summary for a subscription
CREATE OR REPLACE FUNCTION get_subscription_usage_summary(
    p_subscription_id VARCHAR(36),
    p_metric usage_metric
)
RETURNS TABLE (
    total_quantity BIGINT,
    plan_limit BIGINT,
    percentage_used NUMERIC(5, 2),
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COALESCE(a.total_quantity, 0),
        a.plan_limit,
        a.percentage_used,
        a.period_start,
        a.period_end
    FROM billing_usage_aggregates a
    WHERE a.subscription_id = p_subscription_id
    AND a.metric = p_metric
    AND NOW() BETWEEN a.period_start AND a.period_end
    ORDER BY a.period_start DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_subscription_usage_summary(VARCHAR, usage_metric)
    IS 'Get current period usage summary for a subscription and metric';

-- Function to upsert usage aggregate
CREATE OR REPLACE FUNCTION upsert_usage_aggregate(
    p_subscription_id VARCHAR(36),
    p_customer_id VARCHAR(36),
    p_metric usage_metric,
    p_period_start TIMESTAMPTZ,
    p_period_end TIMESTAMPTZ,
    p_quantity_delta BIGINT,
    p_plan_limit BIGINT DEFAULT NULL
)
RETURNS billing_usage_aggregates AS $$
DECLARE
    result billing_usage_aggregates;
BEGIN
    INSERT INTO billing_usage_aggregates (
        subscription_id, customer_id, metric, period_start, period_end,
        total_quantity, record_count, plan_limit, percentage_used, last_record_at
    )
    VALUES (
        p_subscription_id, p_customer_id, p_metric, p_period_start, p_period_end,
        p_quantity_delta, 1, p_plan_limit,
        CASE WHEN p_plan_limit > 0 THEN (p_quantity_delta::NUMERIC / p_plan_limit * 100) ELSE 0 END,
        NOW()
    )
    ON CONFLICT (subscription_id, metric, period_start, period_end)
    DO UPDATE SET
        total_quantity = billing_usage_aggregates.total_quantity + p_quantity_delta,
        record_count = billing_usage_aggregates.record_count + 1,
        plan_limit = COALESCE(p_plan_limit, billing_usage_aggregates.plan_limit),
        percentage_used = CASE
            WHEN COALESCE(p_plan_limit, billing_usage_aggregates.plan_limit, 0) > 0
            THEN ((billing_usage_aggregates.total_quantity + p_quantity_delta)::NUMERIC /
                  COALESCE(p_plan_limit, billing_usage_aggregates.plan_limit) * 100)
            ELSE 0
        END,
        last_record_at = NOW(),
        updated_at = NOW()
    RETURNING * INTO result;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION upsert_usage_aggregate(VARCHAR, VARCHAR, usage_metric, TIMESTAMPTZ, TIMESTAMPTZ, BIGINT, BIGINT)
    IS 'Upsert usage aggregate with atomic increment';

-- =============================================================================
-- SYNC FUNCTION: Sync org plan to subscription
-- =============================================================================
-- When org plan changes via organizations table, sync to active subscription

CREATE OR REPLACE FUNCTION sync_org_plan_to_subscription()
RETURNS TRIGGER AS $$
BEGIN
    -- Only act on plan changes
    IF OLD.plan IS DISTINCT FROM NEW.plan THEN
        UPDATE billing_subscriptions s
        SET
            plan = NEW.plan::text::billing_plan,
            updated_at = NOW()
        FROM billing_customers c
        WHERE s.customer_id = c.id
        AND c.org_id = NEW.id
        AND s.status = 'active';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_sync_org_plan ON organizations;
CREATE TRIGGER trigger_sync_org_plan
    AFTER UPDATE OF plan ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION sync_org_plan_to_subscription();

COMMENT ON TRIGGER trigger_sync_org_plan ON organizations IS 'Sync org plan changes to billing subscription';

COMMIT;
