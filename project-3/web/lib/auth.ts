// Supabase Auth (email magic link). The backend verifies the access token and allows only the owner's email.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export const DEV_AUTH = process.env.NEXT_PUBLIC_NEXUS_DEV_AUTH === "1"; // local only: backend runs with NEXUS_DEV_USER

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient | null {
  if (DEV_AUTH || !url || !anonKey) return null;
  client ??= createClient(url, anonKey, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } });
  return client;
}

export async function accessToken(): Promise<string | null> {
  const sb = supabase();
  if (!sb) return null;
  const { data } = await sb.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function sendMagicLink(email: string): Promise<string | null> {
  const sb = supabase();
  if (!sb) return "Sign-in is not configured.";
  const { error } = await sb.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin, shouldCreateUser: false } });
  return error ? error.message : null;
}

export async function signInWithPassword(email: string, password: string): Promise<string | null> {
  const sb = supabase();
  if (!sb) return "Sign-in is not configured.";
  const { error } = await sb.auth.signInWithPassword({ email, password });
  return error ? error.message : null;
}

export async function signOut(): Promise<void> {
  await supabase()?.auth.signOut();
}
