/**
 * Master data — Pajak and Gaji/Tunjangan.
 *
 * The two lists finance sets up once and then picks from everywhere else.
 * Both are short, so both are edited in place: one row per entry, the form
 * on top, and the accounts named rather than numbered because nobody
 * remembers that 2103 is PPN Keluaran.
 *
 * The tax half asks for two accounts, and that is the point of the screen.
 * The same tax is a liability when we charge it to a customer and an asset
 * when a supplier charges it to us; one row holds both so an invoice only
 * has to name the tax.
 *
 * The payroll half asks for a type, and the type is what the amount cannot
 * say: whether it is paid or deducted, and whether it moves the PPh 21 base.
 * The chips on each row show both, because "Potongan Gaji (Tidak Mengurangi
 * PPh)" and "Pengurangan Gaji (Mengurangi PPh)" are otherwise the same word
 * twice.
 */
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Receipt, Wallet, Loader2, Plus, Trash2, AlertCircle, CheckCircle2, X,
  Pencil, Check,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { AccountPicker } from "@/components/AccountPicker";
import { useT } from "@/store/lang";

interface TaxRow {
  id: string; kind: string; kind_label: string; description: string;
  rate_pct: number;
  sales_account_no: string | null; sales_account_name?: string | null;
  purchase_account_no: string | null; purchase_account_name?: string | null;
  is_active: boolean; notes: string | null;
}
interface PayRow {
  id: string; name: string; kind: string; kind_label: string;
  direction: "pay" | "deduct"; taxable: boolean; regular: boolean;
  account_no: string | null; account_name?: string | null;
  default_amount: number; is_active: boolean; notes: string | null;
}
interface KindOption {
  value: string; label: string;
  direction?: string; taxable?: boolean; regular?: boolean;
}

const idr = (n: number) =>
  new Intl.NumberFormat("id-ID", { maximumFractionDigits: 2 }).format(n || 0);

export default function MasterDataPage() {
  const t = useT();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"tax" | "pay">("tax");
  const [flash, setFlash] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // One timer, not one per message. Without cancelling the previous one, an
  // older "Saved." still owns a dismiss due in two seconds and takes the
  // refusal that replaced it down with it — so a save that was rejected
  // looks like a save that vanished.
  const timer = useRef<number | null>(null);
  const say = (kind: "ok" | "err", text: string) => {
    setFlash({ kind, text });
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setFlash(null), 6000);
  };
  // The API wraps refusals in an envelope, and the refusals here are the
  // useful part — "there is already a PPN called that", "2101 is a heading".
  // Reading only `message` off the axios error would show "status code 409",
  // which tells nobody anything.
  const blame = (e: any) =>
    say("err", e?.response?.data?.errors?.[0]?.message
      ?? e?.response?.data?.detail
      ?? t("That did not save.", "Gagal menyimpan."));

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">
          {t("Master data", "Data induk")}
        </h1>
        <p className="text-xs muted">
          {t("Set these up once; the rest of the books pick from them.",
             "Atur sekali; sisanya tinggal memilih.")}
        </p>
      </header>

      {flash && (
        <div className={clsx(
          "flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
          flash.kind === "ok"
            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
            : "border-rose-200 bg-rose-50 text-rose-800")}>
          {flash.kind === "ok" ? <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
                               : <AlertCircle size={15} className="mt-0.5 shrink-0" />}
          <span className="flex-1">{flash.text}</span>
          <button onClick={() => setFlash(null)} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      )}

      <div className="flex gap-1 border-b border-ink-200">
        {([
          ["tax", t("Tax", "Pajak"), Receipt],
          ["pay", t("Salary/allowance", "Gaji/Tunjangan"), Wallet],
        ] as const).map(([key, label, Icon]) => (
          <button key={key} onClick={() => setTab(key)}
            className={clsx(
              "flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px",
              tab === key
                ? "border-brand-600 text-brand-700 font-medium"
                : "border-transparent muted hover:text-ink-700")}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === "tax" ? <TaxTab say={say} blame={blame} qc={qc} />
                     : <PayTab say={say} blame={blame} qc={qc} />}
    </div>
  );
}

/* ------------------------------------------------------------------ Pajak */

function TaxTab({ say, blame, qc }: {
  say: (k: "ok" | "err", s: string) => void;
  blame: (e: any) => void;
  qc: ReturnType<typeof useQueryClient>;
}) {
  const t = useT();
  const [kind, setKind] = useState("ppn");
  const [description, setDescription] = useState("");
  const [rate, setRate] = useState("");
  const [salesAcc, setSalesAcc] = useState("");
  const [purchaseAcc, setPurchaseAcc] = useState("");
  const [editing, setEditing] = useState<string | null>(null);

  const kinds = useQuery({
    queryKey: ["tax-kinds"],
    queryFn: () => api.get("/master/tax-types/kinds")
      .then((r) => r.data as KindOption[]),
    staleTime: 5 * 60_000,
  });
  const list = useQuery({
    queryKey: ["tax-types"],
    queryFn: () => api.get("/master/tax-types").then((r) => r.data as TaxRow[]),
  });

  const reset = () => {
    setKind("ppn"); setDescription(""); setRate("");
    setSalesAcc(""); setPurchaseAcc(""); setEditing(null);
  };

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        kind, description,
        rate_pct: Number(rate || 0),
        sales_account_no: salesAcc || null,
        purchase_account_no: purchaseAcc || null,
      };
      return editing
        ? api.patch(`/master/tax-types/${editing}`, body).then((r) => r.data)
        : api.post("/master/tax-types", body).then((r) => r.data);
    },
    onSuccess: () => {
      say("ok", editing ? t("Saved.", "Tersimpan.")
                        : t("Tax added.", "Pajak ditambahkan."));
      reset();
      qc.invalidateQueries({ queryKey: ["tax-types"] });
    },
    onError: blame,
  });

  const toggle = useMutation({
    mutationFn: (row: TaxRow) =>
      api.patch(`/master/tax-types/${row.id}`, { is_active: !row.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tax-types"] }),
    onError: blame,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/master/tax-types/${id}`),
    onSuccess: () => {
      say("ok", t("Removed.", "Dihapus."));
      qc.invalidateQueries({ queryKey: ["tax-types"] });
    },
    onError: blame,
  });

  const edit = (row: TaxRow) => {
    setEditing(row.id);
    setKind(row.kind);
    setDescription(row.description);
    setRate(String(row.rate_pct ?? ""));
    setSalesAcc(row.sales_account_no ?? "");
    setPurchaseAcc(row.purchase_account_no ?? "");
  };

  const rows = list.data ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <section className="card p-4 space-y-3 h-fit">
        <h2 className="text-sm font-semibold">
          {editing ? t("Edit tax", "Ubah pajak") : t("New tax", "Pajak baru")}
        </h2>

        <label className="block">
          <span className="label">{t("Type", "Jenis Pajak")}</span>
          <select className="input" value={kind} aria-label="Tax kind"
            onChange={(e) => setKind(e.target.value)}>
            {(kinds.data ?? []).map((k) => (
              <option key={k.value} value={k.value}>{k.label}</option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="label">{t("Description", "Keterangan")}</span>
          <input className="input" value={description} aria-label="Keterangan"
            placeholder={t("e.g. PPN Keluaran 11%", "mis. PPN Keluaran 11%")}
            onChange={(e) => setDescription(e.target.value)} />
        </label>

        <label className="block">
          <span className="label">{t("Rate (%)", "Tarif (%)")}</span>
          <input className="input" type="number" step="0.01" min="0" max="100"
            value={rate} aria-label="Rate"
            onChange={(e) => setRate(e.target.value)} />
        </label>

        <div>
          <span className="label">
            {t("Sales tax account", "Akun Pajak Penjualan")}
          </span>
          <AccountPicker value={salesAcc} onChange={setSalesAcc}
            ariaLabel="Akun Pajak Penjualan" />
          <p className="text-[11px] muted mt-1">
            {t("What we charge a customer — we are holding it for the state.",
               "Yang kita tagih ke pelanggan — kita menitipkannya untuk negara.")}
          </p>
        </div>

        <div>
          <span className="label">
            {t("Purchase tax account", "Akun Pajak Pembelian")}
          </span>
          <AccountPicker value={purchaseAcc} onChange={setPurchaseAcc}
            ariaLabel="Akun Pajak Pembelian" />
          <p className="text-[11px] muted mt-1">
            {t("What a supplier charges us — we claim it back.",
               "Yang ditagih pemasok ke kita — bisa dikreditkan kembali.")}
          </p>
        </div>

        <div className="flex gap-2 pt-1">
          <button className="btn-primary flex-1"
            disabled={!description.trim() || save.isPending}
            onClick={() => save.mutate()}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" />
                            : editing ? <Check size={14} /> : <Plus size={14} />}
            {editing ? t("Save", "Simpan") : t("Add", "Tambah")}
          </button>
          {editing && (
            <button className="btn-ghost" onClick={reset}>
              {t("Cancel", "Batal")}
            </button>
          )}
        </div>
      </section>

      <section className="card overflow-hidden">
        {list.isLoading ? (
          <div className="p-6 flex justify-center">
            <Loader2 className="animate-spin" size={18} />
          </div>
        ) : !rows.length ? (
          <p className="p-6 text-sm muted">
            {t("No taxes set up yet.", "Belum ada pajak.")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50 text-xs uppercase muted">
                <tr>
                  <th className="text-left px-3 py-2">{t("Type", "Jenis")}</th>
                  <th className="text-left px-3 py-2">{t("Description", "Keterangan")}</th>
                  <th className="text-right px-3 py-2">{t("Rate", "Tarif")}</th>
                  <th className="text-left px-3 py-2">{t("Sales acct.", "Akun jual")}</th>
                  <th className="text-left px-3 py-2">{t("Purchase acct.", "Akun beli")}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={clsx(
                    "border-t border-ink-100",
                    !r.is_active && "opacity-50")}>
                    <td className="px-3 py-2">{r.kind_label}</td>
                    <td className="px-3 py-2 font-medium">{r.description}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {idr(r.rate_pct)}%
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.sales_account_no
                        ? <><span className="font-mono">{r.sales_account_no}</span>
                            {" "}{r.sales_account_name}</>
                        : <span className="muted">—</span>}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.purchase_account_no
                        ? <><span className="font-mono">{r.purchase_account_no}</span>
                            {" "}{r.purchase_account_name}</>
                        : <span className="muted">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <button className="btn-ghost px-2 py-1"
                          aria-label={`Edit ${r.description}`}
                          onClick={() => edit(r)}>
                          <Pencil size={13} />
                        </button>
                        <button className="btn-ghost px-2 py-1 text-xs"
                          aria-label={`Toggle ${r.description}`}
                          onClick={() => toggle.mutate(r)}>
                          {r.is_active ? t("Off", "Nonaktif") : t("On", "Aktif")}
                        </button>
                        <button className="btn-ghost px-2 py-1 text-rose-600"
                          aria-label={`Delete ${r.description}`}
                          onClick={() => remove.mutate(r.id)}>
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/* ---------------------------------------------------------- Gaji/Tunjangan */

function PayTab({ say, blame, qc }: {
  say: (k: "ok" | "err", s: string) => void;
  blame: (e: any) => void;
  qc: ReturnType<typeof useQueryClient>;
}) {
  const t = useT();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("gaji");
  const [account, setAccount] = useState("");
  const [amount, setAmount] = useState("");
  const [editing, setEditing] = useState<string | null>(null);

  const kinds = useQuery({
    queryKey: ["pay-kinds"],
    queryFn: () => api.get("/master/pay-components/kinds")
      .then((r) => r.data as KindOption[]),
    staleTime: 5 * 60_000,
  });
  const list = useQuery({
    queryKey: ["pay-components"],
    queryFn: () => api.get("/master/pay-components")
      .then((r) => r.data as PayRow[]),
  });

  const chosen = (kinds.data ?? []).find((k) => k.value === kind);
  const reset = () => {
    setName(""); setKind("gaji"); setAccount(""); setAmount(""); setEditing(null);
  };

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name, kind, account_no: account || null,
        default_amount: Number(amount || 0),
      };
      return editing
        ? api.patch(`/master/pay-components/${editing}`, body).then((r) => r.data)
        : api.post("/master/pay-components", body).then((r) => r.data);
    },
    onSuccess: () => {
      say("ok", editing ? t("Saved.", "Tersimpan.")
                        : t("Component added.", "Komponen ditambahkan."));
      reset();
      qc.invalidateQueries({ queryKey: ["pay-components"] });
    },
    onError: blame,
  });

  const toggle = useMutation({
    mutationFn: (row: PayRow) =>
      api.patch(`/master/pay-components/${row.id}`, { is_active: !row.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pay-components"] }),
    onError: blame,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/master/pay-components/${id}`),
    onSuccess: () => {
      say("ok", t("Removed.", "Dihapus."));
      qc.invalidateQueries({ queryKey: ["pay-components"] });
    },
    onError: blame,
  });

  const edit = (row: PayRow) => {
    setEditing(row.id);
    setName(row.name);
    setKind(row.kind);
    setAccount(row.account_no ?? "");
    setAmount(String(row.default_amount ?? ""));
  };

  const rows = list.data ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <section className="card p-4 space-y-3 h-fit">
        <h2 className="text-sm font-semibold">
          {editing ? t("Edit component", "Ubah komponen")
                   : t("New component", "Komponen baru")}
        </h2>

        <label className="block">
          <span className="label">{t("Name", "Nama")}</span>
          <input className="input" value={name} aria-label="Component name"
            placeholder={t("e.g. Tunjangan Transport", "mis. Tunjangan Transport")}
            onChange={(e) => setName(e.target.value)} />
        </label>

        <label className="block">
          <span className="label">{t("Type", "Jenis Gaji/Tunjangan")}</span>
          <select className="input" value={kind} aria-label="Pay kind"
            onChange={(e) => setKind(e.target.value)}>
            {(kinds.data ?? []).map((k) => (
              <option key={k.value} value={k.value}>{k.label}</option>
            ))}
          </select>
        </label>

        {chosen && (
          <div className="flex flex-wrap gap-1.5 text-[11px]">
            <span className={clsx(
              "px-1.5 py-0.5 rounded",
              chosen.direction === "pay"
                ? "bg-emerald-50 text-emerald-700"
                : "bg-rose-50 text-rose-700")}>
              {chosen.direction === "pay" ? t("Paid to employee", "Menambah")
                                          : t("Deducted", "Mengurangi")}
            </span>
            <span className={clsx(
              "px-1.5 py-0.5 rounded",
              chosen.taxable ? "bg-amber-50 text-amber-700"
                             : "bg-ink-100 text-ink-600")}>
              {chosen.taxable ? t("Moves PPh 21 base", "Mempengaruhi dasar PPh 21")
                              : t("No PPh 21 effect", "Tidak mempengaruhi PPh 21")}
            </span>
            {!chosen.regular && (
              <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700">
                {t("Irregular income", "Penghasilan tidak teratur")}
              </span>
            )}
          </div>
        )}

        <div>
          <span className="label">{t("Account", "Akun Beban")}</span>
          <AccountPicker value={account} onChange={setAccount}
            ariaLabel="Akun Beban" />
        </div>

        <label className="block">
          <span className="label">{t("Default amount", "Nilai bawaan")}</span>
          <input className="input" type="number" min="0" step="1"
            value={amount} aria-label="Default amount"
            onChange={(e) => setAmount(e.target.value)} />
          <p className="text-[11px] muted mt-1">
            {t("Optional. An employee's own figure still wins.",
               "Opsional. Nilai per karyawan tetap yang dipakai.")}
          </p>
        </label>

        <div className="flex gap-2 pt-1">
          <button className="btn-primary flex-1"
            disabled={!name.trim() || save.isPending}
            onClick={() => save.mutate()}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" />
                            : editing ? <Check size={14} /> : <Plus size={14} />}
            {editing ? t("Save", "Simpan") : t("Add", "Tambah")}
          </button>
          {editing && (
            <button className="btn-ghost" onClick={reset}>
              {t("Cancel", "Batal")}
            </button>
          )}
        </div>
      </section>

      <section className="card overflow-hidden">
        {list.isLoading ? (
          <div className="p-6 flex justify-center">
            <Loader2 className="animate-spin" size={18} />
          </div>
        ) : !rows.length ? (
          <p className="p-6 text-sm muted">
            {t("No components set up yet.", "Belum ada komponen.")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-ink-50 text-xs uppercase muted">
                <tr>
                  <th className="text-left px-3 py-2">{t("Name", "Nama")}</th>
                  <th className="text-left px-3 py-2">{t("Type", "Jenis")}</th>
                  <th className="text-left px-3 py-2">{t("Account", "Akun")}</th>
                  <th className="text-right px-3 py-2">{t("Default", "Bawaan")}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={clsx(
                    "border-t border-ink-100",
                    !r.is_active && "opacity-50")}>
                    <td className="px-3 py-2">
                      <div className="font-medium flex items-center gap-1.5">
                        <span className={clsx(
                          "font-mono",
                          r.direction === "pay" ? "text-emerald-600"
                                                : "text-rose-600")}>
                          {r.direction === "pay" ? "+" : "−"}
                        </span>
                        {r.name}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.kind_label}
                      {r.taxable && (
                        <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-amber-50 text-amber-700">
                          {t("PPh 21", "PPh 21")}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.account_no
                        ? <><span className="font-mono">{r.account_no}</span>
                            {" "}{r.account_name}</>
                        : <span className="muted">—</span>}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {r.default_amount ? idr(r.default_amount)
                                        : <span className="muted">—</span>}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <button className="btn-ghost px-2 py-1"
                          aria-label={`Edit ${r.name}`}
                          onClick={() => edit(r)}>
                          <Pencil size={13} />
                        </button>
                        <button className="btn-ghost px-2 py-1 text-xs"
                          aria-label={`Toggle ${r.name}`}
                          onClick={() => toggle.mutate(r)}>
                          {r.is_active ? t("Off", "Nonaktif") : t("On", "Aktif")}
                        </button>
                        <button className="btn-ghost px-2 py-1 text-rose-600"
                          aria-label={`Delete ${r.name}`}
                          onClick={() => remove.mutate(r.id)}>
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
