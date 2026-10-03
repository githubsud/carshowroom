/**
 * Production build values: public only (Supabase URL, publishable key, API URL).
 * The free test deployment (docs/RUNBOOK.md §6): Supabase Frankfurt + Render.
 */
export const environment = {
  production: true,
  supabaseUrl: 'https://dzwfmotqnwyeuddwrkwf.supabase.co',
  // Project Settings → API Keys → "Publishable key" (sb_publishable_...). Public by design.
  supabasePublishableKey: 'sb_publishable_EWWzb3yv3t1jUEcxp2hg7Q_ofPCyKfb',
  apiBaseUrl: 'https://sayyara-api.onrender.com/api/v1',
};
