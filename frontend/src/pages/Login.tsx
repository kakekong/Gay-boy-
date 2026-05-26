import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Factory, ArrowRight, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const t = await api.post("/auth/login", { email, password });
      setTokens(t.data.access_token, t.data.refresh_token);
      const me = await api.get("/auth/me");
      setUser(me.data);
      const role = me.data?.role;
      if (role === "customer")      nav("/portal");
      else if (role === "supplier") nav("/supplier-portal");
      else                          nav("/");
    } catch (e: any) {
      setErr(e.response?.data?.errors?.[0]?.message ?? "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-full grid lg:grid-cols-2 bg-ink-50">
      {/* Brand panel */}
      <div className="relative hidden lg:flex flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-700 via-brand-600 to-brand-500 text-white p-12">
        <div className="absolute -top-32 -right-32 h-96 w-96 rounded-full bg-white/10 blur-3xl" />
        <div className="absolute bottom-0 -left-20 h-72 w-72 rounded-full bg-brand-300/30 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <div className="h-11 w-11 rounded-xl bg-white/15 backdrop-blur flex items-center justify-center">
            <Factory size={22} />
          </div>
          <div>
            <div className="text-xl font-semibold">Transmisi Eng</div>
            <div className="text-xs uppercase tracking-widest text-white/70">
              Project ERP · AI · WhatsApp
            </div>
          </div>
        </div>

        <div className="relative space-y-6">
          <h1 className="text-4xl font-bold leading-tight">
            Run your factory's whole sales journey from one screen.
          </h1>
          <p className="text-white/80 max-w-md">
            CRM · Quotations · Purchasing · Operations · Finance — wired together
            and watched over by an AI Command Center that flags risk, ranks your
            day, and writes WhatsApp follow-ups for you.
          </p>
          <div className="flex flex-wrap gap-2">
            {["Mining", "PLTU", "Cement", "Sugar", "Pulp & Paper", "Food"].map((t) => (
              <span
                key={t}
                className="rounded-full bg-white/10 backdrop-blur px-3 py-1 text-xs"
              >
                {t}
              </span>
            ))}
          </div>
        </div>

        <div className="relative text-xs text-white/60">
          © {new Date().getFullYear()} Transmisi Eng
        </div>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center p-6 sm:p-10">
        <form
          onSubmit={submit}
          className="w-full max-w-sm card p-8 space-y-5"
        >
          <div className="space-y-1">
            <div className="lg:hidden flex items-center gap-2 mb-3">
              <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center">
                <Factory size={18} className="text-white" />
              </div>
              <span className="font-semibold">Transmisi Eng</span>
            </div>
            <h2 className="section-title">Welcome back</h2>
            <p className="text-sm muted">Sign in to continue.</p>
          </div>

          <div className="space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-ink-600">Email</span>
              <input
                className="input mt-1"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                autoComplete="email"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-ink-600">Password</span>
              <input
                type="password"
                className="input mt-1"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </label>
          </div>

          {err && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
              {err}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="btn-primary w-full disabled:opacity-60"
          >
            {busy ? <Loader2 className="animate-spin" size={16} /> : <ArrowRight size={16} />}
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
