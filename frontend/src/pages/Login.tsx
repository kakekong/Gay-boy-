import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Factory, ArrowRight, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";
import { useT, useLangStore } from "@/store/lang";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);
  const lastLogoutReason = useAuthStore((s) => s.lastLogoutReason);
  const clearLogoutReason = useAuthStore((s) => s.clearLogoutReason);
  const nav = useNavigate();
  const t = useT();
  const lang = useLangStore((s) => s.lang);
  const setLang = useLangStore((s) => s.setLang);

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
      setErr(e.response?.data?.errors?.[0]?.message ?? t("Login failed", "Gagal masuk"));
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
            {t(
              "Run your factory's whole sales journey from one screen.",
              "Jalankan seluruh proses penjualan pabrik Anda dari satu layar."
            )}
          </h1>
          <p className="text-white/80 max-w-md">
            {t(
              "CRM · Quotations · Purchasing · Operations · Finance — wired together and watched over by an AI Command Center that flags risk, ranks your day, and writes WhatsApp follow-ups for you.",
              "CRM · Penawaran · Pembelian · Operasi · Keuangan — terhubung dan diawasi oleh AI Command Center yang menandai risiko, mengurutkan tugas harian, dan menulis pesan WhatsApp tindak lanjut untuk Anda."
            )}
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
            <div className="flex items-start justify-between gap-2">
              <h2 className="section-title">{t("Welcome back", "Selamat datang kembali")}</h2>
              <button
                type="button"
                onClick={() => setLang(lang === "en" ? "id" : "en")}
                className="text-[10px] font-semibold uppercase tracking-wider text-ink-500 border border-ink-200 rounded px-2 py-1 hover:bg-ink-50"
                title={lang === "en" ? "Bahasa Indonesia" : "English"}
              >
                {lang === "en" ? "EN · ID" : "ID · EN"}
              </button>
            </div>
            <p className="text-sm muted">{t("Sign in to continue.", "Masuk untuk melanjutkan.")}</p>
          </div>

          <div className="space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-ink-600">{t("Email", "Email")}</span>
              <input
                className="input mt-1"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                autoComplete="email"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-ink-600">{t("Password", "Kata sandi")}</span>
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

          {lastLogoutReason && !err && (
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
              <div className="font-semibold mb-0.5">
                {t("You were signed out", "Anda telah keluar")}
              </div>
              <div>{lastLogoutReason}</div>
              <button
                type="button"
                onClick={clearLogoutReason}
                className="mt-1 text-amber-700 underline hover:no-underline"
              >
                {t("Dismiss", "Tutup")}
              </button>
            </div>
          )}

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
            {busy ? t("Signing in…", "Memproses…") : t("Sign in", "Masuk")}
          </button>

          <button
            type="button"
            onClick={() => {
              try { localStorage.clear(); } catch {}
              try { sessionStorage.clear(); } catch {}
              window.location.reload();
            }}
            className="text-[11px] text-ink-400 hover:text-ink-700 underline w-full text-center"
            title={t(
              "Wipe any leftover login data from older app versions and reload",
              "Hapus data login dari versi lama dan muat ulang"
            )}
          >
            {t(
              "Trouble signing in? Reset cached data",
              "Bermasalah masuk? Bersihkan data tersimpan"
            )}
          </button>

          <div className="text-[10px] text-ink-300 text-center font-mono">
            build {__BUILD_STAMP__}
          </div>
        </form>
      </div>
    </div>
  );
}
