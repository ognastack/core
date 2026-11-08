-- migrate:up
-- supabase/auth enables row-level security on auth.sessions without adding
-- policies, so every role except the table owner sees zero rows. The gateway
-- then treats every session as ended and rejects all tokens with 401.
-- Let the read-only gateway login see sessions (it can only SELECT anyway).
DROP POLICY IF EXISTS ogna_gateway_read_sessions ON auth.sessions;
CREATE POLICY ogna_gateway_read_sessions ON auth.sessions
  FOR SELECT TO ogna_gateway USING (true);

-- migrate:down
DROP POLICY IF EXISTS ogna_gateway_read_sessions ON auth.sessions;
