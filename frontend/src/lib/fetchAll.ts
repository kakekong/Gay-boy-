import { api } from "@/api/client";

/** Every customer the filter matches, page after page until the total is met.
 *
 *  `/customers` pages (500 at most per request), and a dropdown or board that
 *  asked for one page of 200 quietly lost every customer after the 200th —
 *  nothing on screen said anything was missing. Returns the same
 *  `{ data, total }` shape a single page does, so callers don't change. */
export async function fetchAllCustomers<T = any>(
  params: Record<string, unknown> = {},
): Promise<{ data: T[]; total: number }> {
  const all: T[] = [];
  const size = 500;
  let total = 0;
  for (let page = 1; ; page++) {
    const r = await api.get("/customers", { params: { ...params, page, page_size: size } });
    const rows: T[] = r.data?.data ?? [];
    total = r.data?.total ?? all.length + rows.length;
    all.push(...rows);
    if (!rows.length || all.length >= total) break;
  }
  return { data: all, total };
}
