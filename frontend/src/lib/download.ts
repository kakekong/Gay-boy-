import { api } from "@/api/client";

/** Read a (possibly blob) error response into a human message. */
async function readBlobError(e: any): Promise<string> {
  const status = e?.response?.status;
  const blob: Blob | undefined = e?.response?.data;
  let detail = "";
  if (blob && typeof blob.text === "function") {
    try {
      const text = await blob.text();
      try {
        const parsed = JSON.parse(text);
        detail = parsed?.detail ?? parsed?.errors?.[0]?.message ?? text;
      } catch {
        detail = text;
      }
    } catch { /* ignore */ }
  }
  if (!detail) detail = e?.message ?? "Download failed";
  return status ? `Download failed (HTTP ${status}): ${detail}` : detail;
}

/** GET an authenticated file endpoint and save it to disk. */
export function downloadFile(url: string, filename: string, params?: Record<string, any>) {
  return api.get(url, { responseType: "blob", params })
    .then((r) => {
      const objectUrl = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    })
    .catch(async (e) => {
      // eslint-disable-next-line no-console
      console.error("download failed", url, e);
      alert(await readBlobError(e));
    });
}
