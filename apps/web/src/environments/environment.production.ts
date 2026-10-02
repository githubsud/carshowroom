/**
 * Production build values. Replace the placeholders in the deployment pipeline;
 * only public values belong here (Supabase URL, publishable key, API URL).
 */
export const environment = {
  production: true,
  supabaseUrl: 'https://YOUR-PROJECT.supabase.co',
  supabasePublishableKey: 'YOUR-PUBLISHABLE-KEY',
  apiBaseUrl: 'https://api.example.com/api/v1',
};
