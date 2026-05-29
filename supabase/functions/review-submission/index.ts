/**
 * Banyan — review-submission Edge Function
 *
 * Handles approve and reject actions for pending org submissions.
 * Runs server-side with the Supabase service role key so the
 * public anon key never needs write access to organizations.
 *
 * Called by: docs/dashboard.html (password-gated admin UI)
 * Auth: token field must match DASHBOARD_SECRET env var
 *
 * Deploy:
 *   supabase secrets set DASHBOARD_SECRET="your-dashboard-password"
 *   supabase functions deploy review-submission
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

const ORG_FIELDS = [
  "name", "description", "website_url", "email",
  "twitter_url", "facebook_url", "instagram_url",
  "state", "service_area", "scope_of_service",
  "year_founded", "has_membership", "num_members",
  "services", "communities_served", "primary_contact",
];

Deno.serve(async (req: Request) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS });
  }

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { ...CORS, "Content-Type": "application/json" },
    });

  try {
    const {
      token,
      action,
      sub_id,
      org_data = {},
      reviewer_notes = null,
    } = await req.json();

    // ── Auth ────────────────────────────────────────────────────
    const secret = Deno.env.get("DASHBOARD_SECRET") ?? "";
    if (!secret || token !== secret) {
      return json({ error: "Unauthorized" }, 401);
    }

    // ── Admin client (service role — bypasses RLS) ──────────────
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL") ?? "",
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
    );

    // ── Fetch submission ────────────────────────────────────────
    const { data: sub, error: subErr } = await supabase
      .from("pending_submissions")
      .select("*")
      .eq("id", sub_id)
      .single();

    if (subErr || !sub) {
      return json({ error: "Submission not found" }, 404);
    }

    if (sub.status !== "pending") {
      return json({ error: `Submission already ${sub.status}` }, 409);
    }

    // ── Reject ──────────────────────────────────────────────────
    if (action === "reject") {
      const { error } = await supabase
        .from("pending_submissions")
        .update({
          status: "rejected",
          reviewed_at: new Date().toISOString(),
          reviewer_notes: reviewer_notes || null,
        })
        .eq("id", sub_id);

      if (error) return json({ error: error.message }, 500);
      return json({ ok: true });
    }

    // ── Approve ─────────────────────────────────────────────────
    if (action === "approve") {
      // Build org record from dashboard-edited values (org_data),
      // falling back to original submission values for any field
      // the admin didn't touch.
      const merged: Record<string, unknown> = {};
      for (const field of ORG_FIELDS) {
        const edited = (org_data as Record<string, unknown>)[field];
        const original = (sub as Record<string, unknown>)[field];
        const value = edited !== undefined ? edited : original;
        if (value != null && value !== "" && !(Array.isArray(value) && value.length === 0)) {
          merged[field] = value;
        }
      }

      if (sub.submission_type === "new_org") {
        const { error } = await supabase.from("organizations").insert(merged);
        if (error) return json({ error: error.message }, 500);
      } else if (sub.submission_type === "edit_org" && sub.org_id) {
        const { error } = await supabase
          .from("organizations")
          .update(merged)
          .eq("id", sub.org_id);
        if (error) return json({ error: error.message }, 500);
      }

      const { error: statusErr } = await supabase
        .from("pending_submissions")
        .update({
          status: "approved",
          reviewed_at: new Date().toISOString(),
          reviewer_notes: reviewer_notes || null,
        })
        .eq("id", sub_id);

      if (statusErr) return json({ error: statusErr.message }, 500);
      return json({ ok: true });
    }

    return json({ error: "Invalid action — use 'approve' or 'reject'" }, 400);

  } catch (e) {
    return json({ error: String(e) }, 500);
  }
});
