import { Injectable } from '@angular/core';
import { createClient, SupabaseClient } from '@supabase/supabase-js';

import { environment } from '../../../environments/environment';

/**
 * The single Supabase client: authentication and RLS-protected reads.
 * Money never moves through it (SPEC §3.1); that goes through the API.
 */
@Injectable({ providedIn: 'root' })
export class SupabaseService {
  readonly client: SupabaseClient = createClient(environment.supabaseUrl, environment.supabasePublishableKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      // Invitation and password-recovery links land on /reset-password with a session in the URL.
      detectSessionInUrl: true,
    },
  });
}
