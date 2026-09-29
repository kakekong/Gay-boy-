import { T } from "@/store/lang";

/** "Showing 50 of 312 · Load more" under a list that loads a page at a time.
 *
 *  A list that stops at a fixed number of rows has to say so — otherwise
 *  rows past the cap are simply missing and nobody can tell. Pass `total`
 *  when the server counts; without it, a full page (`shown` rows back) is
 *  taken to mean there may be more. Renders nothing once everything is in. */
export function LoadMore({ shown, loaded, total, fetching, onMore }: {
  shown: number;
  loaded: number;
  total?: number | null;
  fetching?: boolean;
  onMore: () => void;
}) {
  const more = total != null ? total > loaded : loaded >= shown;
  if (!more) return null;
  return (
    <div className="px-5 py-3 border-t border-ink-100 flex items-center justify-between gap-3 flex-wrap">
      <span className="text-xs muted">
        {T("Showing")} {loaded}{total != null && <> {T("of")} {total}</>}
      </span>
      <button className="btn-ghost" disabled={fetching} onClick={onMore}>
        {fetching ? T("Loading…") : T("Load more")}
      </button>
    </div>
  );
}
