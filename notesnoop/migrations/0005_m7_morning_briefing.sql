-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

CREATE OR REPLACE FUNCTION notesnoop.disable_morning_briefing(
  target_workspace_id UUID,
  target_user_id TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = notesnoop, pg_temp
AS $$
DECLARE
  changed_count INTEGER := 0;
BEGIN
  UPDATE notesnoop.workspace_members
  SET morning_briefing_optin = FALSE
  WHERE workspace_id = target_workspace_id
    AND clerk_user_id = target_user_id
    AND morning_briefing_optin = TRUE;

  GET DIAGNOSTICS changed_count = ROW_COUNT;
  RETURN changed_count > 0;
END;
$$;

CREATE OR REPLACE FUNCTION notesnoop.disable_morning_briefing_by_email(
  target_email TEXT
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = notesnoop, pg_temp
AS $$
DECLARE
  changed_count INTEGER := 0;
BEGIN
  UPDATE notesnoop.workspace_members wm
  SET morning_briefing_optin = FALSE
  FROM notesnoop.user_profiles up
  WHERE up.clerk_user_id = wm.clerk_user_id
    AND lower(up.email) = lower(target_email)
    AND wm.morning_briefing_optin = TRUE;

  GET DIAGNOSTICS changed_count = ROW_COUNT;
  RETURN changed_count;
END;
$$;

GRANT EXECUTE ON FUNCTION notesnoop.disable_morning_briefing(UUID, TEXT) TO notesnoop_app, notesnoop_worker;
GRANT EXECUTE ON FUNCTION notesnoop.disable_morning_briefing_by_email(TEXT) TO notesnoop_app, notesnoop_worker;

COMMENT ON FUNCTION notesnoop.disable_morning_briefing(UUID, TEXT) IS
  'Unauthenticated one-click unsubscribe helper. Narrow SECURITY DEFINER path only flips the Morning briefing opt-in flag.';
COMMENT ON FUNCTION notesnoop.disable_morning_briefing_by_email(TEXT) IS
  'Postmark bounce helper. Narrow SECURITY DEFINER path suppresses Morning briefing for memberships attached to a bounced address.';
