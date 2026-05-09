-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=60s

DROP POLICY IF EXISTS flags_owner_returning_select ON flags;
CREATE POLICY flags_owner_returning_select ON flags
  FOR SELECT
  USING (flagged_user_id = current_user_id() AND is_workspace_member(workspace_id));

DROP POLICY IF EXISTS inbound_email_log_owner_address_access ON inbound_email_log;
CREATE POLICY inbound_email_log_owner_address_access ON inbound_email_log
  USING (
    EXISTS (
      SELECT 1
      FROM inbound_email_addresses iea
      WHERE iea.address = inbound_email_log.recipient_address
        AND iea.clerk_user_id = current_user_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM inbound_email_addresses iea
      WHERE iea.address = inbound_email_log.recipient_address
        AND iea.clerk_user_id = current_user_id()
    )
  );
