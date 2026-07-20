const SOLR = "/solr/meastlib/select";

export async function searchPages(query, { rows = 20, start = 0 } = {}) {
  const params = new URLSearchParams({
    q: `ocr_text:(${query})`,
    hl: "on",
    "hl.ocr.fl": "ocr_text",
    "hl.snippets": "3",
    rows: String(rows),
    start: String(start),
    wt: "json",
  });
  const r = await fetch(`${SOLR}?${params}`);
  if (!r.ok) throw new Error(`Solr ${r.status}`);
  const data = await r.json();
  const ocrHl = data.ocrHighlighting || {};
  return {
    total: data.response?.numFound ?? 0,
    hits: (data.response?.docs || []).map((doc) => ({
      id: doc.id,
      itemId: doc.item_id,
      page: doc.page,
      title: doc.title || doc.item_id,
      creator: doc.creator,
      date: doc.date_published,
      snippets: (ocrHl[doc.id]?.ocr_text?.snippets || []).map((s) => s.text),
    })),
  };
}

export async function fetchManifest(itemId) {
  const r = await fetch(`/data/items/${itemId}/iiif/manifest.json`);
  if (!r.ok) throw new Error(`Manifest ${r.status}`);
  return r.json();
}

export async function fetchPageText(itemId, page) {
  const r = await fetch(`/data/items/${itemId}/ocr/${page}.txt`);
  return r.ok ? r.text() : "";
}

export function pageNumber(page) {
  return parseInt(String(page).replace("page-", ""), 10) || 1;
}

export function pageId(n) {
  return `page-${String(n).padStart(4, "0")}`;
}

async function adminJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

export function fetchAdminItems() {
  return adminJson("/api/items");
}

export function fetchAdminJobs() {
  return adminJson("/api/jobs");
}

export function fetchAdminTools() {
  return adminJson("/api/tools");
}

export function uploadBook(formData) {
  return adminJson("/api/items", { method: "POST", body: formData });
}

export function analyzeBookMetadata(file) {
  const formData = new FormData();
  formData.append("file", file);
  return adminJson("/api/metadata/analyze", { method: "POST", body: formData });
}

export function runItemAction(itemId, action, ocrLanguages = "ara+fas") {
  const params = new URLSearchParams({ ocr_languages: ocrLanguages });
  return adminJson(`/api/items/${encodeURIComponent(itemId)}/actions/${action}?${params}`, {
    method: "POST",
  });
}

export function cancelAdminJob(jobId) {
  return adminJson(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

export function clearFinishedAdminJobs() {
  return adminJson("/api/jobs", { method: "DELETE" });
}
