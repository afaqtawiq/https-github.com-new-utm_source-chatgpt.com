"""Additive operational subledger. Never migrates CRM or shipment amounts."""
from app.storage import db

LOCK_KEY = 73002051


def init_storage():
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))
        c.execute('''CREATE TABLE IF NOT EXISTS finance_parties(
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('owner','counterparty')),
            identity_ref TEXT NOT NULL, confirmed BOOLEAN NOT NULL DEFAULT FALSE,
            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(kind,identity_ref), CHECK(length(trim(name))>0), CHECK(length(trim(identity_ref))>0))''')
        c.execute('''CREATE TABLE IF NOT EXISTS finance_documents(
            id BIGSERIAL PRIMARY KEY, owner_id BIGINT NOT NULL REFERENCES finance_parties(id),
            counterparty_id BIGINT NOT NULL REFERENCES finance_parties(id),
            kind TEXT NOT NULL CHECK(kind IN ('opening_receivable','claim','payable','expense','receipt','payment','receivable_adjustment','payable_adjustment')),
            currency TEXT NOT NULL DEFAULT '', source_amount NUMERIC(20,8) NOT NULL CHECK(source_amount>0),
            source_amount_raw TEXT NOT NULL, amount_minor BIGINT, document_date DATE,
            source_ref TEXT NOT NULL, source_locator TEXT NOT NULL, economic_ref TEXT NOT NULL,
            source_role TEXT NOT NULL CHECK(source_role IN ('detail','summary')),
            source_date_raw TEXT NOT NULL DEFAULT '', source_status_raw TEXT NOT NULL DEFAULT '',
            source_verification TEXT NOT NULL DEFAULT 'recorded' CHECK(source_verification IN ('recorded','independently_verified')),
            verification_ref TEXT NOT NULL DEFAULT '', source_cached_external BOOLEAN NOT NULL DEFAULT FALSE,
            invoice_ref TEXT NOT NULL DEFAULT '', customs_ref TEXT NOT NULL DEFAULT '',
            shipment_id BIGINT REFERENCES shipments(id), amount_basis TEXT NOT NULL CHECK(amount_basis IN ('gross','net','unknown')),
            notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','reviewed','posted','reversed','void')),
            supersedes_id BIGINT REFERENCES finance_documents(id),
            idempotency_key UUID NOT NULL UNIQUE, payload_hash TEXT NOT NULL,
            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,
            reviewed_by BIGINT REFERENCES users(id), reviewed_at TIMESTAMPTZ, rounding_ack BOOLEAN NOT NULL DEFAULT FALSE,
            posted_by BIGINT REFERENCES users(id), posted_at TIMESTAMPTZ,
            reversed_by BIGINT REFERENCES users(id), reversed_at TIMESTAMPTZ, reversal_reason TEXT NOT NULL DEFAULT '',
            CHECK(owner_id<>counterparty_id), CHECK(amount_minor IS NULL OR amount_minor>=0),
            CHECK(status NOT IN ('reviewed','posted','reversed') OR (currency<>'' AND document_date IS NOT NULL AND amount_minor>0 AND source_role='detail')))''')
        # Additive upgrade: never rewrite existing evidence or journal history.
        c.execute("ALTER TABLE finance_documents ADD COLUMN IF NOT EXISTS opening_cutoff DATE")
        c.execute("ALTER TABLE finance_documents ADD COLUMN IF NOT EXISTS opening_confirmation_ref TEXT NOT NULL DEFAULT ''")
        c.execute("ALTER TABLE finance_documents ADD COLUMN IF NOT EXISTS opening_review_ack BOOLEAN NOT NULL DEFAULT FALSE")
        c.execute('ALTER TABLE finance_documents DROP CONSTRAINT IF EXISTS finance_documents_kind_check')
        c.execute("ALTER TABLE finance_documents ADD CONSTRAINT finance_documents_kind_check CHECK(kind IN ('opening_receivable','claim','payable','expense','receipt','payment','receivable_adjustment','payable_adjustment'))")
        # Find only the original automatically named status/source CHECK, or its
        # named replacement on subsequent initializations.
        c.execute('''DO $$ DECLARE constraint_row record; BEGIN
          FOR constraint_row IN SELECT conname FROM pg_constraint
            WHERE conrelid='finance_documents'::regclass AND contype='c'
              AND pg_get_constraintdef(oid) LIKE '%status%'
              AND pg_get_constraintdef(oid) LIKE '%source_role%'
              AND pg_get_constraintdef(oid) LIKE '%document_date%'
          LOOP EXECUTE format('ALTER TABLE finance_documents DROP CONSTRAINT %I', constraint_row.conname); END LOOP;
        END $$''')
        c.execute('''ALTER TABLE finance_documents ADD CONSTRAINT finance_document_postable CHECK(
          status NOT IN ('reviewed','posted','reversed') OR
          (currency<>'' AND document_date IS NOT NULL AND amount_minor>0 AND
            ((kind<>'opening_receivable' AND source_role='detail') OR
             (kind='opening_receivable' AND source_role='summary' AND amount_basis='net'
              AND opening_cutoff IS NOT NULL AND opening_cutoff=document_date
              AND length(trim(opening_confirmation_ref))>0 AND opening_review_ack
              AND invoice_ref='' AND customs_ref='' AND shipment_id IS NULL))))''')
        c.execute('ALTER TABLE finance_documents DROP CONSTRAINT IF EXISTS finance_opening_fields')
        c.execute('''ALTER TABLE finance_documents ADD CONSTRAINT finance_opening_fields CHECK(
          kind='opening_receivable' OR (opening_cutoff IS NULL AND opening_confirmation_ref='' AND NOT opening_review_ack))''')
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS finance_active_opening ON finance_documents(owner_id,counterparty_id,currency) WHERE kind='opening_receivable' AND status='posted'")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS finance_active_source ON finance_documents(owner_id,source_ref,source_locator,kind) WHERE status NOT IN ('void','reversed')")
        # Reversed/void evidence may be superseded, retaining the original source locator. Active duplicates cannot post.
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS finance_active_event ON finance_documents(owner_id,counterparty_id,kind,economic_ref) WHERE status='posted'")
        c.execute('''CREATE TABLE IF NOT EXISTS finance_entries(
            id BIGSERIAL PRIMARY KEY, document_id BIGINT NOT NULL REFERENCES finance_documents(id),
            phase TEXT NOT NULL CHECK(phase IN ('posting','reversal')),
            side TEXT NOT NULL CHECK(side IN ('receivable','payable')), signed_minor BIGINT NOT NULL CHECK(signed_minor<>0),
            actor_id BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(document_id,phase))''')
        c.execute('''CREATE TABLE IF NOT EXISTS finance_allocations(
            id BIGSERIAL PRIMARY KEY, credit_id BIGINT NOT NULL REFERENCES finance_documents(id),
            document_id BIGINT NOT NULL REFERENCES finance_documents(id), amount_minor BIGINT NOT NULL CHECK(amount_minor>0),
            idempotency_key UUID NOT NULL UNIQUE, payload_hash TEXT NOT NULL,
            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,
            reversed_at TIMESTAMPTZ, CHECK(credit_id<>document_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS finance_audit(
            id BIGSERIAL PRIMARY KEY, actor_id BIGINT NOT NULL REFERENCES users(id),
            action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id BIGINT NOT NULL,
            detail TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS finance_entitlement_rules(
            id BIGSERIAL PRIMARY KEY, owner_id BIGINT NOT NULL REFERENCES finance_parties(id),
            company_scope TEXT NOT NULL, rate NUMERIC(7,4) NOT NULL CHECK(rate>0 AND rate<=100),
            basis TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'inactive' CHECK(status='inactive'),
            idempotency_key UUID NOT NULL UNIQUE, payload_hash TEXT NOT NULL,
            created_by BIGINT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS finance_pair_currency ON finance_documents(owner_id,counterparty_id,currency)')
        c.execute('CREATE INDEX IF NOT EXISTS finance_credit_allocations ON finance_allocations(credit_id) WHERE reversed_at IS NULL')
        c.execute('CREATE INDEX IF NOT EXISTS finance_document_allocations ON finance_allocations(document_id) WHERE reversed_at IS NULL')
        c.execute('CREATE INDEX IF NOT EXISTS finance_entity_audit ON finance_audit(entity_type,entity_id,id DESC)')
        c.execute('''CREATE OR REPLACE FUNCTION finance_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Finance evidence and entries are immutable'; END; $$''')
        for table in ('finance_entries', 'finance_audit', 'finance_parties', 'finance_entitlement_rules'):
            c.execute('DROP TRIGGER IF EXISTS immutable_finance_row ON '+table)
            c.execute('CREATE TRIGGER immutable_finance_row BEFORE UPDATE OR DELETE ON '+table+' FOR EACH ROW EXECUTE FUNCTION finance_immutable()')
        c.execute('''CREATE OR REPLACE FUNCTION finance_preserve_document() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Finance evidence cannot be deleted'; END IF;
            IF OLD.status<>NEW.status AND NOT ((OLD.status='draft' AND NEW.status IN ('reviewed','void')) OR (OLD.status='reviewed' AND NEW.status IN ('posted','void')) OR (OLD.status='posted' AND NEW.status='reversed'))
              THEN RAISE EXCEPTION 'Invalid finance document transition'; END IF;
            IF (to_jsonb(NEW)-ARRAY['status','reviewed_by','reviewed_at','rounding_ack','opening_review_ack','posted_by','posted_at','reversed_by','reversed_at','reversal_reason'])
              IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','reviewed_by','reviewed_at','rounding_ack','opening_review_ack','posted_by','posted_at','reversed_by','reversed_at','reversal_reason'])
              THEN RAISE EXCEPTION 'Original finance evidence cannot be overwritten'; END IF;
            RETURN NEW;
          END; $$''')
        c.execute('DROP TRIGGER IF EXISTS preserve_finance_document ON finance_documents')
        c.execute('CREATE TRIGGER preserve_finance_document BEFORE UPDATE OR DELETE ON finance_documents FOR EACH ROW EXECUTE FUNCTION finance_preserve_document()')
        c.execute('''CREATE OR REPLACE FUNCTION finance_preserve_allocation() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Finance allocation cannot be deleted'; END IF;
            IF (to_jsonb(NEW)-'reversed_at') IS DISTINCT FROM (to_jsonb(OLD)-'reversed_at') OR OLD.reversed_at IS NOT NULL OR NEW.reversed_at IS NULL
              THEN RAISE EXCEPTION 'Finance allocation is immutable'; END IF;
            RETURN NEW;
          END; $$''')
        c.execute('DROP TRIGGER IF EXISTS preserve_finance_allocation ON finance_allocations')
        c.execute('CREATE TRIGGER preserve_finance_allocation BEFORE UPDATE OR DELETE ON finance_allocations FOR EACH ROW EXECUTE FUNCTION finance_preserve_allocation()')
