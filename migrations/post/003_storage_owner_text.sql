-- migrate:up
-- Users now come from Zitadel, whose ids are strings and which keeps its own
-- database. For installs that ran the GoTrue-era 002 migration, drop the
-- foreign key to auth.users and store the owner as text. No-op on fresh installs.
ALTER TABLE storage.bucket DROP CONSTRAINT IF EXISTS fk_owner;
ALTER TABLE storage.bucket ALTER COLUMN owner TYPE TEXT USING owner::text;

-- migrate:down
-- Not reversible safely: Zitadel ids are not UUIDs.
