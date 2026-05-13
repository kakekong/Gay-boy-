import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api } from "@/api/client";
import { TagChip } from "@/components/TagChip";
import type { TagRecord } from "@/components/TagManager";

interface Props {
  userId: string;
  attachedTagIds: string[];
}

export function TagPicker({ userId, attachedTagIds }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const tags = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.get("/tags").then((r) => r.data as TagRecord[]),
    enabled: open,
  });

  const attach = useMutation({
    mutationFn: (tag_id: string) =>
      api.post(`/tags/users/${userId}`, { tag_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["user-tags", userId] });
      qc.invalidateQueries({ queryKey: ["employees"] });
      setOpen(false);
      setSearch("");
    },
  });

  const available = (tags.data ?? [])
    .filter((t) => !attachedTagIds.includes(t.id))
    .filter((t) => !search || t.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="chip bg-ink-100 text-ink-600 hover:bg-ink-200 px-2 py-0.5"
      >
        <Plus size={11} /> Add tag
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-7 z-40 w-64 rounded-xl bg-white shadow-card border border-ink-100 p-2">
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search tags…"
              className="input mb-2"
            />
            <div className="max-h-56 overflow-y-auto space-y-1">
              {available.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => attach.mutate(t.id)}
                  className="w-full text-left p-1.5 rounded hover:bg-ink-50 flex items-center gap-2"
                >
                  <TagChip name={t.name} color={t.color} />
                </button>
              ))}
              {!available.length && (
                <div className="px-2 py-3 text-xs muted text-center">
                  {tags.isLoading ? "Loading…"
                    : (tags.data ?? []).length === 0
                      ? "No tags exist yet. HR / Director can create some via 'Manage tags' on the Employees page."
                      : "No more tags to add."}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
