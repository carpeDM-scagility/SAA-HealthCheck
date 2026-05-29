-- Banyan — RLS Security Fix
-- Run this in Supabase SQL Editor AFTER add_submissions_table.sql
-- Removes the four dangerous open-write policies and replaces them
-- with server-side-only writes via the Edge Function.

-- ── 1. Drop dangerous write policies on organizations ─────────────
-- These allowed anyone with the public anon key to INSERT or UPDATE
-- any org in the directory — bypassing the review queue entirely.
DROP POLICY IF EXISTS "orgs_anon_insert" ON organizations;
DROP POLICY IF EXISTS "orgs_anon_update" ON organizations;

-- ── 2. Drop dangerous write policies on pending_submissions ───────
-- These allowed anyone to approve their own submission or delete
-- submissions before they were reviewed.
DROP POLICY IF EXISTS "public_update" ON pending_submissions;
DROP POLICY IF EXISTS "public_delete" ON pending_submissions;

-- ── 3. What remains (intentional) ────────────────────────────────
-- organizations:
--   SELECT (anon)  → public directory reads + contact reveal feature  ✓
--   INSERT / UPDATE → service role only (Edge Function)               ✓
--
-- pending_submissions:
--   INSERT (anon)  → community can submit new orgs / corrections      ✓
--   SELECT (anon)  → dashboard can load the review queue              ✓
--   UPDATE / DELETE → service role only (Edge Function)               ✓

-- ── 4. Verify remaining policies ─────────────────────────────────
SELECT schemaname, tablename, policyname, cmd
FROM pg_policies
WHERE tablename IN ('organizations', 'pending_submissions')
ORDER BY tablename, cmd;
