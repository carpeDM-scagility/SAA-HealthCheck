/**
 * Banyan — trigger-rebuild Edge Function
 *
 * Fires the regenerate-site GitHub Actions workflow so newly approved
 * orgs appear on the public directory without a manual terminal run.
 *
 * Auth: token must match DASHBOARD_SECRET (same as review-submission).
 * Secrets required:
 *   DASHBOARD_SECRET  — dashboard password
 *   GITHUB_PAT        — fine-grained PAT with Actions: read+write on SAA-HealthCheck
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

const REPO     = "carpeDM-scagility/SAA-HealthCheck";
const WORKFLOW = "regenerate-site.yml";

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS });
  }

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { ...CORS, "Content-Type": "application/json" },
    });

  try {
    const { token } = await req.json();

    // Validate dashboard token
    const secret = Deno.env.get("DASHBOARD_SECRET") ?? "";
    if (!secret || token !== secret) {
      return json({ error: "Unauthorized" }, 401);
    }

    // Trigger GitHub Actions workflow dispatch
    const ghPat = Deno.env.get("GITHUB_PAT") ?? "";
    if (!ghPat) {
      return json({ error: "GITHUB_PAT secret not set" }, 500);
    }

    const res = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          "Authorization":        `Bearer ${ghPat}`,
          "Accept":               "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type":         "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );

    // GitHub returns 204 No Content on success
    if (!res.ok) {
      const err = await res.text();
      return json({ error: `GitHub API error ${res.status}: ${err}` }, 500);
    }

    return json({
      ok: true,
      message: "Rebuild triggered — site will update in about 1 minute.",
    });

  } catch (e) {
    return json({ error: String(e) }, 500);
  }
});
