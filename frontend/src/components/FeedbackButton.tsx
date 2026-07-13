import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Loader2, MessageSquarePlus, Send } from "lucide-react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { useT, t as tt } from "@/store/lang";

/** A direct line to the director — visible to every account. Captures the
 *  page the sender was on so issues are easy to reproduce. */
export function FeedbackButton({ compact = false }: { compact?: boolean }) {
  const t = useT();
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);

  const send = useMutation({
    mutationFn: () => api.post("/feedback", {
      message: message.trim(),
      page: loc.pathname,
    }),
    onSuccess: () => {
      setSent(true);
      setMessage("");
      setTimeout(() => { setSent(false); setOpen(false); }, 1800);
    },
    onError: (e: any) => alert(
      e?.response?.data?.errors?.[0]?.message
      ?? tt("Failed to send feedback.", "Gagal mengirim masukan."),
    ),
  });

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={compact
          ? "p-2 rounded-lg text-ink-500 hover:bg-ink-100 hover:text-ink-800"
          : "w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-600 hover:bg-ink-100"}
        title={t("Send feedback to the director", "Kirim masukan ke direktur")}
      >
        <MessageSquarePlus size={compact ? 18 : 15} />
        {!compact && t("Send feedback", "Kirim masukan")}
      </button>

      {open && (
        <Modal
          open={open}
          onClose={() => setOpen(false)}
          title={t("Send feedback", "Kirim masukan")}
        >
          {sent ? (
            <div className="p-4 text-center text-sm text-emerald-700">
              ✅ {t("Sent — the director will see it.", "Terkirim — direktur akan melihatnya.")}
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-xs muted">
                {t(
                  "Goes straight to the director — bugs, ideas, anything that slows you down. Your name and this page are attached automatically.",
                  "Langsung ke direktur — bug, ide, apa pun yang menghambat Anda. Nama Anda dan halaman ini terlampir otomatis.",
                )}
              </p>
              <textarea
                className="input min-h-[120px]"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder={t("What's on your mind?", "Apa yang ingin Anda sampaikan?")}
                autoFocus
              />
              <div className="flex justify-end gap-2">
                <button className="btn-ghost" onClick={() => setOpen(false)}>
                  {t("Cancel", "Batal")}
                </button>
                <button
                  className="btn-primary"
                  disabled={message.trim().length < 3 || send.isPending}
                  onClick={() => send.mutate()}
                >
                  {send.isPending
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Send size={14} />}
                  {t("Send", "Kirim")}
                </button>
              </div>
            </div>
          )}
        </Modal>
      )}
    </>
  );
}
