-- SAA Org Health Tracker — Community Submissions
-- Run this in Supabase SQL Editor

-- ── 1. Pending submissions table ────────────────────────────────
CREATE TABLE IF NOT EXISTS pending_submissions (
  id                UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  submission_type   TEXT        NOT NULL CHECK (submission_type IN ('new_org', 'edit_org')),
  status            TEXT        NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'approved', 'rejected')),

  -- For edit submissions: reference to existing org
  org_id            UUID        REFERENCES organizations(id) ON DELETE SET NULL,
  existing_org_name TEXT,       -- denormalized copy for display even if org changes

  -- Submitter info
  submitter_name    TEXT,
  submitter_email   TEXT,
  submitter_notes   TEXT,

  -- Proposed org field values
  name              TEXT,
  description       TEXT,
  website_url       TEXT,
  email             TEXT,
  facebook_url      TEXT,
  instagram_url     TEXT,
  twitter_url       TEXT,
  state             TEXT,
  service_area      TEXT,
  scope_of_service  TEXT,
  year_founded      INTEGER,
  has_membership    BOOLEAN,
  services          TEXT[],
  communities_served TEXT[],
  primary_contact   TEXT,

  -- Review
  reviewer_notes    TEXT,
  reviewed_at       TIMESTAMPTZ
);

-- ── 2. RLS on pending_submissions ────────────────────────────────
ALTER TABLE pending_submissions ENABLE ROW LEVEL SECURITY;

-- Public can submit new entries
CREATE POLICY "public_insert" ON pending_submissions
  FOR INSERT WITH CHECK (true);

-- Anyone can read (dashboard is JS-password-gated)
CREATE POLICY "public_select" ON pending_submissions
  FOR SELECT USING (true);

-- Dashboard can update status (approve/reject)
CREATE POLICY "public_update" ON pending_submissions
  FOR UPDATE USING (true);

-- Dashboard can delete rejected/old entries
CREATE POLICY "public_delete" ON pending_submissions
  FOR DELETE USING (true);

-- ── 3. RLS on organizations (needed for anon-key approval writes) ─
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;

-- Allow public reads (select)
CREATE POLICY "orgs_public_read" ON organizations
  FOR SELECT USING (true);

-- Allow inserts for approved new-org submissions
CREATE POLICY "orgs_anon_insert" ON organizations
  FOR INSERT WITH CHECK (true);

-- Allow updates for approved edit submissions
CREATE POLICY "orgs_anon_update" ON organizations
  FOR UPDATE USING (true);

-- ── 4. Verify ────────────────────────────────────────────────────
SELECT table_name, COUNT(*) as policy_count
FROM information_schema.table_privileges
WHERE table_name IN ('pending_submissions','organizations')
GROUP BY table_name;
