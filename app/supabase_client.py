"""
Singleton Supabase client using the service-role key.
Service role bypasses RLS — all authorization happens in the API layer.
"""

from supabase import create_client, Client
from app.config import settings

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

# supabase-py registers an auth-state listener that replaces the PostgREST
# Authorization header with the signed-in user's access token whenever
# sign_in_with_password (or similar) is called.  On a service-role-only
# server that breaks all subsequent DB writes with RLS errors.  We clear the
# listener so the header always stays as the service-role key.
supabase.auth._state_change_emitters.clear()
