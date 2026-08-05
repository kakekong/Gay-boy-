import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { useT, t as tt, T } from "@/store/lang";

const TYPES = [
  "call", "presentation", "technical_meeting", "purchase_request",
  "quotation_sent", "negotiation", "follow_up", "whatsapp_out",
  "email", "note",
];

// Indonesian display labels for the activity type values. Display only —
// the raw values are still what gets sent to the API.
const TYPE_LABEL_ID: Record<string, string> = {
  call: "telepon",
  presentation: "presentasi",
  technical_meeting: "meeting teknis",
  purchase_request: "permintaan pembelian",
  quotation_sent: "penawaran terkirim",
  negotiation: "negosiasi",
  follow_up: "tindak lanjut",
  whatsapp_out: "WhatsApp keluar",
  email: "email",
  note: "catatan",
};

interface Props {
  customerId: string;
  onClose: () => void;
}

export function LogActivityForm({ customerId, onClose }: Props) {
  const t = useT();
  const qc = useQueryClient();
  const [type, setType] = useState("call");
  const [direction, setDirection] = useState("outbound");
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.post(`/customers/${customerId}/activities`, {
      type, direction, notes,
    }).then((r) => r.data),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["activities", customerId] });
      qc.invalidateQueries({ queryKey: ["approvals"] });
      // Sales follow-ups are held for director approval.
      if (data?.status === "pending_approval") {
        setInfo(data?.message ?? tt(
          "Follow-up sent to the director for approval.",
          "Tindak lanjut dikirim ke direktur untuk persetujuan.",
        ));
        return;
      }
      onClose();
    },
    onError: (e: any) => {
      setErr(e?.response?.data?.errors?.[0]?.message
        ?? tt("Failed to log activity", "Gagal mencatat aktivitas"));
    },
  });

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); setErr(null); create.mutate(); }}
      className="space-y-4"
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("Type", "Tipe")}>
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            {TYPES.map((ty) => (
              <option key={ty} value={ty}>
                {t(ty.replace(/_/g, " "), TYPE_LABEL_ID[ty] ?? ty)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("Direction", "Arah")}>
          <select className="input" value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="outbound">{t("outbound", "keluar")}</option>
            <option value="inbound">{t("inbound", "masuk")}</option>
            <option value="internal">{t("internal", "internal")}</option>
          </select>
        </Field>
      </div>
      <Field label={t("Notes", "Catatan")}>
        <textarea
          className="input min-h-[100px]"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder={t(
            "What happened? Decisions, next steps…",
            "Apa yang terjadi? Keputusan, langkah selanjutnya…",
          )}
        />
      </Field>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700">
          {err}
        </div>
      )}

      {info && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-800">
          {info}
        </div>
      )}

      <div className="flex justify-end gap-2">
        {info ? (
          <button type="button" className="btn-primary" onClick={onClose}>{t("Close", "Tutup")}</button>
        ) : (
          <>
            <button type="button" className="btn-ghost" onClick={onClose}>{t("Cancel", "Batal")}</button>
            <button type="submit" className="btn-primary" disabled={create.isPending}>
              {create.isPending && <Loader2 size={14} className="animate-spin" />}
              {create.isPending ? t("Saving…", "Menyimpan…") : t("Save activity", "Simpan aktivitas")}
            </button>
          </>
        )}
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-1">{T(label)}</span>
      {children}
    </label>
  );
}
