
-- Create the checks schema
CREATE SCHEMA IF NOT EXISTS storage;

CREATE TABLE storage.bucket (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    owner UUID,

    -- Adding the foreign key constraint
    CONSTRAINT fk_owner
        FOREIGN KEY (owner)
        REFERENCES auth.users(id)
        ON DELETE CASCADE
);

CREATE TABLE storage.object (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    bucket_id UUID NOT NULL,
    last_modified TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Foreign Key Constraint
    CONSTRAINT fk_bucket
        FOREIGN KEY (bucket_id)
        REFERENCES storage.bucket(id)
        ON DELETE CASCADE
);

-- Index for the name column as specified in your SQLModel (index=True)
CREATE INDEX ix_storage_object_name ON storage.object (name);

ALTER TABLE storage.object ADD CONSTRAINT object_bucket_id_name_key UNIQUE (bucket_id, name);