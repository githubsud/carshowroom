/**
 * Development defaults: match `supabase start` and the local API.
 * The publishable key is designed to be public; the service-role / secret key
 * must never appear in this app (SPEC §10).
 */
export const environment = {
  production: false,
  supabaseUrl: 'http://127.0.0.1:54321',
  supabasePublishableKey: 'sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH',
  apiBaseUrl: 'http://localhost:8000/api/v1',
};
