-- DataSnoop staging scrub policy.
--
-- SCRUB_INVENTORY_BEGIN
-- public_reference: activity, address, administrator, affiliation
-- public_reference: aggregator_skiplist, branch, code, company_info, contact
-- public_reference: denomination, enterprise, establishment, financial_by_year
-- public_reference: financial_data, financial_latest, insolvency_case
-- public_reference: juridical_form_category, kbo_extract_log, legal_form_synonyms
-- public_reference: meta, nace_lookup, nace_vlerick_mapping, nbb_load_log
-- public_reference: participating_interest, poll, procurement_award
-- public_reference: schema_migrations, shareholder, staatsblad_backfill_progress
-- public_reference: staatsblad_event, staatsblad_publication
-- public_reference: staatsblad_publication_text, tier_config, vlerick_multiple
-- derived_rebuildable: affiliation_backfill_log, ai_similar_cache
-- derived_rebuildable: company_embedding, company_enrichment, company_popularity
-- derived_rebuildable: extract_log, staatsblad_event_embedding
-- derived_rebuildable: translation_cache, valuation_commentary_cache
-- user_state: ai_insights_feedback, company_view_history, customer_supplier_list
-- user_state: enrichment_job, favourite, favourite_last_checked, favourite_project
-- user_state: favourite_project_member, feedback, people_enrichment
-- user_state: people_favourite, poll_response, staatsblad_bulk_queue
-- user_state: staatsblad_llm_queue, user_digest_log, user_roles
-- secret: activity_log, api_call_log, api_keys, llm_call_log, query_embedding_cache
-- business_state: invoice_misclassification_log, invoice_vendor_pattern
-- business_state: platform_invoice
-- SCRUB_INVENTORY_END
--
-- Classes:
-- - public_reference: public/open data or schema metadata safe to keep in staging.
-- - derived_rebuildable: derived caches that may stay in a full clone but can be
--   rebuilt from public/reference data if a slimmer ad-hoc clone excludes them.
-- - user_state: end-user, queue, response, role, favourite, or upload state.
-- - secret: replayable API material, request logs, LLM logs, or sensitive queries.
-- - business_state: billing, invoice, and accounting-related state.
--
-- The snapshot script applies this file to leadpeek_staging_next before the
-- rename swap. Any missing table is ignored so fresh installs and future
-- partial restores fail only when SQL itself is broken.

DO $$
DECLARE
    scrub_tables text[] := ARRAY[
        'activity_log',
        'ai_insights_feedback',
        'api_call_log',
        'api_keys',
        'company_view_history',
        'customer_supplier_list',
        'enrichment_job',
        'favourite',
        'favourite_last_checked',
        'favourite_project',
        'favourite_project_member',
        'feedback',
        'invoice_misclassification_log',
        'invoice_vendor_pattern',
        'llm_call_log',
        'people_enrichment',
        'people_favourite',
        'platform_invoice',
        'poll_response',
        'query_embedding_cache',
        'staatsblad_bulk_queue',
        'staatsblad_llm_queue',
        'user_digest_log',
        'user_roles'
    ];
    present_tables text[];
BEGIN
    SELECT array_agg(format('public.%I', table_name) ORDER BY table_name)
    INTO present_tables
    FROM unnest(scrub_tables) AS scrub(table_name)
    WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL;

    IF present_tables IS NULL OR array_length(present_tables, 1) IS NULL THEN
        RAISE NOTICE 'staging scrub: no scrub-class tables found';
        RETURN;
    END IF;

    EXECUTE 'TRUNCATE TABLE '
        || array_to_string(present_tables, ', ')
        || ' RESTART IDENTITY CASCADE';

    RAISE NOTICE 'staging scrub: truncated % table(s)', array_length(present_tables, 1);
END $$;
