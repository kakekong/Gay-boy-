import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { GripVertical, Building2, ChevronRight, Eye, EyeOff } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import type { Customer } from "@/types";

const STAGES: { key: string; label: string; tone: string; dot: string }[] = [
  { key: "lead",          label: "Lead",          tone: "bg-ink-100 text-ink-700",        dot: "bg-ink-400"     },
  { key: "presentation",  label: "Presentation",  tone: "bg-blue-50 text-blue-700",       dot: "bg-blue-500"    },
  { key: "engineering",   label: "Engineering",   tone: "bg-indigo-50 text-indigo-700",   dot: "bg-indigo-500"  },
  { key: "quotation",     label: "Quotation",     tone: "bg-violet-50 text-violet-700",   dot: "bg-violet-500"  },
  { key: "negotiation",   label: "Negotiation",   tone: "bg-amber-50 text-amber-700",     dot: "bg-amber-500"   },
  { key: "po",            label: "PO",            tone: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  { key: "drawing",       label: "Drawing",       tone: "bg-cyan-50 text-cyan-700",       dot: "bg-cyan-500"    },
  { key: "purchasing",    label: "Purchasing",    tone: "bg-teal-50 text-teal-700",       dot: "bg-teal-500"    },
  { key: "delivery",      label: "Delivery",      tone: "bg-lime-50 text-lime-700",       dot: "bg-lime-500"    },
  { key: "invoicing",     label: "Invoicing",     tone: "bg-yellow-50 text-yellow-700",   dot: "bg-yellow-500"  },
  { key: "payment",       label: "Payment",       tone: "bg-orange-50 text-orange-700",   dot: "bg-orange-500"  },
  { key: "closed_won",    label: "Won",           tone: "bg-emerald-100 text-emerald-800",dot: "bg-emerald-600" },
  { key: "closed_lost",   label: "Lost",          tone: "bg-red-100 text-red-800",        dot: "bg-red-600"     },
];

const INDUSTRY_TINT: Record<string, string> = {
  mining:     "from-amber-100/60 to-amber-50/60",
  pltu:       "from-orange-100/60 to-yellow-50/60",
  fertilizer: "from-emerald-100/60 to-green-50/60",
  sugar:      "from-pink-100/60 to-rose-50/60",
  cement:     "from-slate-200/70 to-slate-50/70",
  pulp_paper: "from-teal-100/60 to-cyan-50/60",
  food:       "from-lime-100/60 to-emerald-50/60",
  other:      "from-ink-100/60 to-ink-50/60",
};

const INDUSTRY_ICON: Record<string, string> = {
  mining: "⛏️", pltu: "⚡", fertilizer: "🌱", sugar: "🍬",
  cement: "🏗️", pulp_paper: "📰", food: "🍞", other: "🏢",
};

const idr = (n: number) => "Rp " + new Intl.NumberFormat("id-ID").format(n || 0);

interface Props {
  customers: Customer[];
}

export function PipelineView({ customers }: Props) {
  const qc = useQueryClient();
  const [showClosed, setShowClosed] = useState(false);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [hoverStage, setHoverStage] = useState<string | null>(null);
  // On small screens we don't show all 13 columns at once — a stage picker
  // lets the user focus on one column at a time.
  const [mobileStage, setMobileStage] = useState<string>("lead");

  const stages = useMemo(
    () => showClosed
      ? STAGES
      : STAGES.filter((s) => s.key !== "closed_won" && s.key !== "closed_lost"),
    [showClosed]
  );

  const byStage = useMemo(() => {
    const m = new Map<string, Customer[]>();
    for (const c of customers) {
      const arr = m.get(c.stage) ?? [];
      arr.push(c);
      m.set(c.stage, arr);
    }
    return m;
  }, [customers]);

  const sumValue = (arr: Customer[] = []) =>
    arr.reduce((acc, c) => acc + Number(c.lifetime_value || 0), 0);

  const move = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: string }) =>
      api.patch(`/customers/${id}`, { stage }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["customers"] }),
    onError: () => qc.invalidateQueries({ queryKey: ["customers"] }),
  });

  function onDragStart(e: React.DragEvent, id: string) {
    setDraggingId(id);
    e.dataTransfer.setData("text/plain", id);
    e.dataTransfer.effectAllowed = "move";
  }

  function onDrop(e: React.DragEvent, stage: string) {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/plain");
    setDraggingId(null);
    setHoverStage(null);
    if (!id) return;
    const current = customers.find((c) => c.id === id);
    if (!current || current.stage === stage) return;
    // Optimistic update
    qc.setQueryData<any>(["customers", "", ""], (old: any) => {
      if (!old?.data) return old;
      return {
        ...old,
        data: old.data.map((c: Customer) =>
          c.id === id ? { ...c, stage } : c
        ),
      };
    });
    // also update any keyed variants by patching all "customers" queries
    qc.setQueriesData({ queryKey: ["customers"] }, (old: any) => {
      if (!old?.data) return old;
      return {
        ...old,
        data: old.data.map((c: Customer) =>
          c.id === id ? { ...c, stage } : c
        ),
      };
    });
    move.mutate({ id, stage });
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm muted">
          Drag any card to a different stage to move the deal. Sales sees only their own customers.
        </p>
        <button
          onClick={() => setShowClosed((v) => !v)}
          className="btn-ghost"
        >
          {showClosed ? <EyeOff size={14} /> : <Eye size={14} />}
          {showClosed ? "Hide" : "Show"} closed
        </button>
      </div>

      {/* Mobile stage picker */}
      <div className="md:hidden mb-3">
        <select
          className="input"
          value={mobileStage}
          onChange={(e) => setMobileStage(e.target.value)}
        >
          {stages.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label} ({(byStage.get(s.key) ?? []).length})
            </option>
          ))}
        </select>
      </div>

      <div className="overflow-x-auto hidden md:block">
        <div className="flex gap-3 pb-4 min-w-max">
          {stages.map((s) => {
            const items = byStage.get(s.key) ?? [];
            const isHover = hoverStage === s.key;
            return (
              <div
                key={s.key}
                onDragOver={(e) => {
                  e.preventDefault();
                  if (draggingId) setHoverStage(s.key);
                }}
                onDragLeave={() => setHoverStage((prev) => prev === s.key ? null : prev)}
                onDrop={(e) => onDrop(e, s.key)}
                className={clsx(
                  "w-72 shrink-0 rounded-xl border transition-colors",
                  isHover
                    ? "border-brand-400 bg-brand-50/40 ring-2 ring-brand-200"
                    : "border-ink-200 bg-ink-50/40"
                )}
              >
                <div className="px-3 py-2.5 border-b border-ink-100 bg-white rounded-t-xl">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={clsx("h-2 w-2 rounded-full", s.dot)} />
                      <span className="font-semibold text-sm truncate">{s.label}</span>
                      <span className={clsx("chip", s.tone)}>{items.length}</span>
                    </div>
                  </div>
                  {items.length > 0 && (
                    <div className="text-[11px] muted mt-0.5 tabular-nums">
                      {idr(sumValue(items))}
                    </div>
                  )}
                </div>

                <div className="p-2 space-y-2 min-h-[200px]">
                  {items.length === 0 ? (
                    <div className="text-xs muted text-center py-6 italic">
                      Drop here
                    </div>
                  ) : (
                    items.map((c) => {
                      const tint = INDUSTRY_TINT[c.industry] ?? INDUSTRY_TINT.other;
                      const icon = INDUSTRY_ICON[c.industry] ?? "🏢";
                      const isDragging = draggingId === c.id;
                      return (
                        <Link
                          key={c.id}
                          to={`/customers/${c.id}`}
                          draggable
                          onDragStart={(e) => onDragStart(e, c.id)}
                          onDragEnd={() => { setDraggingId(null); setHoverStage(null); }}
                          className={clsx(
                            "block group relative rounded-lg bg-gradient-to-br p-2.5 pl-3",
                            "border border-ink-100 hover:border-brand-300 hover:shadow-soft transition-all",
                            "cursor-grab active:cursor-grabbing",
                            tint,
                            isDragging && "opacity-50 ring-2 ring-brand-300"
                          )}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-start gap-2 min-w-0">
                              <span className="text-base leading-none mt-0.5" aria-hidden>{icon}</span>
                              <div className="min-w-0">
                                <div className="text-sm font-semibold text-ink-900 truncate group-hover:text-brand-700">
                                  {c.company_name}
                                </div>
                                <div className="text-[11px] muted truncate capitalize">
                                  {c.industry.replace(/_/g, " ")}
                                  {c.pic_name && <> · {c.pic_name}</>}
                                </div>
                              </div>
                            </div>
                            <GripVertical
                              size={13}
                              className="text-ink-400 opacity-0 group-hover:opacity-100 shrink-0"
                            />
                          </div>
                          <div className="flex items-center justify-between mt-1.5">
                            <span className="text-[11px] tabular-nums muted">
                              {Number(c.lifetime_value) > 0 ? idr(Number(c.lifetime_value)) : ""}
                            </span>
                            <ChevronRight
                              size={12}
                              className="text-ink-400 opacity-0 group-hover:opacity-100"
                            />
                          </div>
                        </Link>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Mobile: single column for the picked stage */}
      <div className="md:hidden">
        {(() => {
          const s = stages.find((x) => x.key === mobileStage) ?? stages[0];
          const items = byStage.get(s.key) ?? [];
          return (
            <div className="rounded-xl border border-ink-200 bg-ink-50/40">
              <div className="px-3 py-2.5 border-b border-ink-100 bg-white rounded-t-xl">
                <div className="flex items-center gap-2">
                  <span className={clsx("h-2 w-2 rounded-full", s.dot)} />
                  <span className="font-semibold text-sm">{s.label}</span>
                  <span className={clsx("chip", s.tone)}>{items.length}</span>
                </div>
                <div className="text-[11px] muted mt-0.5 tabular-nums">
                  {idr(sumValue(items))}
                </div>
              </div>
              <div className="p-2 space-y-2 min-h-[200px]">
                {items.length === 0 ? (
                  <div className="text-xs muted text-center py-6 italic">
                    No customers in this stage
                  </div>
                ) : (
                  items.map((c) => {
                    const tint = INDUSTRY_TINT[c.industry] ?? INDUSTRY_TINT.other;
                    const icon = INDUSTRY_ICON[c.industry] ?? "🏢";
                    return (
                      <Link
                        key={c.id}
                        to={`/customers/${c.id}`}
                        className={clsx(
                          "block rounded-lg bg-gradient-to-br p-3 border border-ink-100 active:bg-ink-100",
                          tint,
                        )}
                      >
                        <div className="flex items-start gap-2">
                          <span className="text-lg leading-none mt-0.5">{icon}</span>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold truncate">{c.company_name}</div>
                            <div className="text-[11px] muted truncate capitalize">
                              {c.industry.replace(/_/g, " ")}
                              {c.pic_name && <> · {c.pic_name}</>}
                            </div>
                          </div>
                        </div>
                      </Link>
                    );
                  })
                )}
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
