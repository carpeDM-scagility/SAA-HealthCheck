-- SAA Org Health Tracker — Add public directory fields to organizations table
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New query)
-- Safe to run multiple times — all use IF NOT EXISTS

ALTER TABLE organizations
  ADD COLUMN IF NOT EXISTS twitter_url        TEXT,
  ADD COLUMN IF NOT EXISTS description        TEXT,
  ADD COLUMN IF NOT EXISTS year_founded       INTEGER,
  ADD COLUMN IF NOT EXISTS services           TEXT[],
  ADD COLUMN IF NOT EXISTS communities_served TEXT[],
  ADD COLUMN IF NOT EXISTS scope_of_service   TEXT,
  ADD COLUMN IF NOT EXISTS service_area       TEXT,
  ADD COLUMN IF NOT EXISTS has_membership     BOOLEAN,
  ADD COLUMN IF NOT EXISTS num_members        INTEGER,
  ADD COLUMN IF NOT EXISTS primary_contact    TEXT;

-- Optional: add indexes for the array filter columns (speeds up searches)
CREATE INDEX IF NOT EXISTS idx_orgs_services
  ON organizations USING gin (services);

CREATE INDEX IF NOT EXISTS idx_orgs_communities
  ON organizations USING gin (communities_served);

CREATE INDEX IF NOT EXISTS idx_orgs_state
  ON organizations (state);

CREATE INDEX IF NOT EXISTS idx_orgs_scope
  ON organizations (scope_of_service);

-- Verify the new columns exist
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'organizations'
ORDER BY ordinal_position;
