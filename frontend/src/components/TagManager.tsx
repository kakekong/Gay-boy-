import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Loader2, Trash2, Save, Pencil, X as XIcon } from "lucide-react";
import clsx from "clsx";
import { api } from "@/api/client";
import { TAG_COLORS, TagChip, type TagColor } from "@/components/TagChip";
import { T } from "@/store/lang";

export interface TagRecord {
  id: string;
  name: string;
  color: string;
  description: string | null;
  scope: string;
  usage_count: number;
}

export function TagManager({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const tags = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.get("/tags").then((r) => r.data as TagRecord[]),
  });

  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState<TagColor>("brand");
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ name: string; color: TagColor }>({ name: "", color: "brand" });
  const [err, setErr] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.post("/tags", { name: newName, color: newColor }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["employees"] });
      setNewName("");
    },
    onError: (e: any) => setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed"),
  });

  const save = useMutation({
    mutationFn: (id: string) => api.patch(`/tags/${id}`, edit),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["employees"] });
      setEditing(null);
    },
    onError: (e: any) => setErr(e?.response?.data?.errors?.[0]?.message ?? "Failed"),
  });

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/tags/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["employees"] });
    },
  });

  return (
    <div className="space-y-4">
      {/* Create row */}
      <div className="card p-3">
        <div className="text-xs font-semibold uppercase tracking-wider muted mb-2">
          {T("Create a new tag")}</div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex-1 min-w-[180px]">
            <span className="block text-[11px] uppercase muted mb-0.5">{T("Name")}</span>
            <input
              className="input"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={T("e.g. Top performer, Onboarding…")}
            />
          </div>
          <ColorPicker value={newColor} onChange={setNewColor} />
          <button
            className="btn-primary"
            disabled={!newName.trim() || create.isPending}
            onClick={(e) => { e.preventDefault(); setErr(null); create.mutate(); }}
          >
            {create.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {T("Add")}</button>
        </div>
        {newName && (
          <div className="mt-2">
            <span className="text-[11px] muted mr-2">{T("Preview:")}</span>
            <TagChip name={newName} color={newColor} />
          </div>
        )}
      </div>

      {err && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-sm text-red-700 flex items-center justify-between">
          <span>{err}</span>
          <button onClick={() => setErr(null)}><XIcon size={14} /></button>
        </div>
      )}

      {/* List */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-ink-50/60">
            <tr>
              <th className="th">{T("Tag")}</th>
              <th className="th">{T("Color")}</th>
              <th className="th text-right">{T("In use")}</th>
              <th className="th text-right">{T("Actions")}</th>
            </tr>
          </thead>
          <tbody>
            {(tags.data ?? []).map((t) => {
              const isEditing = editing === t.id;
              return (
                <tr key={t.id} className="tr-hover border-t border-ink-100">
                  <td className="td">
                    {isEditing ? (
                      <input
                        className="input max-w-xs"
                        value={edit.name}
                        onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                      />
                    ) : (
                      <TagChip name={t.name} color={t.color} />
                    )}
                  </td>
                  <td className="td">
                    {isEditing ? (
                      <ColorPicker value={edit.color} onChange={(c) => setEdit({ ...edit, color: c })} />
                    ) : (
                      <span className="font-mono text-xs muted">{t.color}</span>
                    )}
                  </td>
                  <td className="td text-right muted">{t.usage_count}</td>
                  <td className="td text-right">
                    <div className="inline-flex gap-1">
                      {isEditing ? (
                        <>
                          <button className="btn-success" onClick={() => save.mutate(t.id)}
                            disabled={save.isPending}>
                            <Save size={13} /> {T("Save")}</button>
                          <button className="btn-ghost" onClick={() => setEditing(null)}>
                            {T("Cancel")}</button>
                        </>
                      ) : (
                        <>
                          <button className="btn-ghost"
                            onClick={() => { setEditing(t.id); setEdit({ name: t.name, color: (t.color as TagColor) ?? "brand" }); }}>
                            <Pencil size={13} />
                          </button>
                          <button className="btn-ghost text-red-600 hover:bg-red-50"
                            onClick={() => {
                              if (window.confirm(`Delete tag "${t.name}"? It will be removed from all employees.`))
                                del.mutate(t.id);
                            }}
                            disabled={del.isPending}>
                            <Trash2 size={13} />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {!tags.data?.length && (
              <tr><td colSpan={4} className="td text-center muted py-8">
                {T("No tags yet. Create one above.")}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex justify-end">
        <button className="btn-primary" onClick={onClose}>{T("Done")}</button>
      </div>
    </div>
  );
}

function ColorPicker({ value, onChange }: {
  value: TagColor;
  onChange: (v: TagColor) => void;
}) {
  return (
    <div>
      <span className="block text-[11px] uppercase muted mb-0.5">{T("Color")}</span>
      <div className="flex flex-wrap gap-1">
        {TAG_COLORS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onChange(c)}
            className={clsx(
              "h-7 w-7 rounded-full ring-2 transition-all",
              value === c ? "ring-ink-700" : "ring-transparent hover:ring-ink-300",
              {
                "bg-brand-500": c === "brand",
                "bg-emerald-500": c === "emerald",
                "bg-amber-500": c === "amber",
                "bg-violet-500": c === "violet",
                "bg-red-500": c === "red",
                "bg-ink-500": c === "ink",
                "bg-blue-500": c === "blue",
                "bg-cyan-500": c === "cyan",
                "bg-lime-500": c === "lime",
                "bg-teal-500": c === "teal",
                "bg-orange-500": c === "orange",
                "bg-pink-500": c === "pink",
              },
            )}
            aria-label={c}
            title={c}
          />
        ))}
      </div>
    </div>
  );
}
