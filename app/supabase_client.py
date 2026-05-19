"""
Singleton Supabase client using the service-role key.
Service role bypasses RLS — all authorization happens in the API layer.
"""

from supabase import create_client, Client
from app.config import settings

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
