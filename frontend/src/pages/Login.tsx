import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { useAuthStore } from "@/store/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("director@demo.local");
  const [password, setPassword] = useState("demo1234");
  const [err, setErr] = useState<string | null>(null);
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const t = await api.post("/auth/login", { email, password });
      setTokens(t.data.access_token, t.data.refresh_token);
      const me = await api.get("/auth/me");
      setUser(me.data);
      nav("/");
    } catch (e: any) {
      setErr(e.response?.data?.errors?.[0]?.message ?? "Login failed");
    }
  }

  return (
    <div className="h-full flex items-center justify-center bg-slate-50">
      <form onSubmit={submit} className="bg-white border rounded-lg p-8 w-96 space-y-3">
        <div className="text-2xl font-semibold mb-2">🏭 IndustriaCRM</div>
        <input
          className="border rounded w-full px-3 py-2 text-sm"
          value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email"
        />
        <input
          type="password"
          className="border rounded w-full px-3 py-2 text-sm"
          value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password"
        />
        {err && <div className="text-sm text-red-600">{err}</div>}
        <button className="w-full bg-brand-500 hover:bg-brand-700 text-white rounded py-2 text-sm">
          Sign in
        </button>
        <div className="text-xs text-slate-500 mt-2">
          Demo: director / manager / sales1 / admin @demo.local — pwd <code>demo1234</code>
        </div>
      </form>
    </div>
  );
}
