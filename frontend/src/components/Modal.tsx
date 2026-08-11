import { useEffect } from "react";
import { X } from "lucide-react";
import { T } from "@/store/lang";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  footer?: React.ReactNode;
  /** Let a click on the dimmed background close this. Off by default: these
   *  dialogs hold typed work, and losing a half-filled supplier or PO to a
   *  stray click beside the box is the most annoying way to lose it. Escape
   *  and the X in the corner still close. Turn it on for anything with
   *  nothing to lose — a picker, a preview. */
  dismissOnBackdrop?: boolean;
}

const SIZE = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
};

export function Modal({
  open, onClose, title, subtitle, children, size = "md", footer,
  dismissOnBackdrop = false,
}: Props) {
  useEffect(() => {
    if (!open) return;
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onEsc);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onEsc);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div
        className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm"
        onClick={dismissOnBackdrop ? onClose : undefined}
      />
      <div className={`relative w-full ${SIZE[size]} bg-white rounded-2xl shadow-card max-h-[90vh] flex flex-col`}>
        <header className="flex items-start justify-between gap-4 px-5 py-4 border-b border-ink-100">
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-ink-900">{title}</h2>
            {subtitle && <p className="text-sm muted mt-0.5">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-ink-400 hover:bg-ink-100 hover:text-ink-700"
            aria-label={T("Close")}
          >
            <X size={18} />
          </button>
        </header>
        <div className="flex-1 overflow-auto p-5">{children}</div>
        {footer && (
          <footer className="border-t border-ink-100 px-5 py-3 bg-ink-50/50 rounded-b-2xl">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
