const SERVICE_URL = (import.meta.env.VITE_SERVICE_URL || "").replace(/\/+$/, "");

export const IS_GITHUB_PAGES = import.meta.env.VITE_GITHUB_PAGES === "true";
export const PUBLIC_PORTAL = import.meta.env.VITE_PUBLIC_PORTAL === "true";
export const SERVICES_AVAILABLE = !IS_GITHUB_PAGES || Boolean(SERVICE_URL);

function serviceUrl(path) {
  return `${SERVICE_URL}${path}`;
}

export function catalogDatasetUrl(path = "/api/catalog/dataset") {
  return serviceUrl(path);
}

export async function searchPages(query, options = {}) {
  const params = new URLSearchParams({ q: query });
  Object.entries({ rows: 10, start: 0, ...options }).forEach(([key, value]) => {
    if (value !== "" && value != null) params.set(key, String(value));
  });
  const r = await fetch(serviceUrl(`/api/search?${params}`));
  if (!r.ok) throw new Error(`Search ${r.status}`);
  return r.json();
}

export async function fetchCatalogItems(options = {}) {
  const params = new URLSearchParams();
  Object.entries(options).forEach(([key, value]) => {
    if (value !== "" && value != null) params.set(key, String(value));
  });
  const r = await fetch(serviceUrl(`/api/catalog/items?${params}`));
  if (!r.ok) throw new Error(`Catalog ${r.status}`);
  return r.json();
}

export async function fetchCatalogItem(itemId) {
  const r = await fetch(serviceUrl(`/api/catalog/items/${encodeURIComponent(itemId)}`));
  if (!r.ok) throw new Error(`Item ${r.status}`);
  return r.json();
}

export async function fetchCollection(collectionId) {
  const r = await fetch(serviceUrl(`/api/catalog/collections/${encodeURIComponent(collectionId)}`));
  if (!r.ok) throw new Error(`Collection ${r.status}`);
  return r.json();
}

export async function fetchArchiveIndex() {
  const r = await fetch(serviceUrl("/api/catalog/archive"));
  if (!r.ok) throw new Error(`Archive ${r.status}`);
  return r.json();
}

export async function fetchAuthority(kind, authorityId) {
  if (!new Set(["authors", "publishers"]).has(kind)) throw new Error("Unknown authority type");
  const r = await fetch(serviceUrl(`/api/catalog/${kind}/${encodeURIComponent(authorityId)}`));
  if (!r.ok) throw new Error(`${kind === "authors" ? "Author" : "Publisher"} ${r.status}`);
  return r.json();
}

export async function searchWithinItem(itemId, query, page = "") {
  const params = new URLSearchParams({ q: query });
  if (page) params.set("page", page);
  const r = await fetch(serviceUrl(`/api/catalog/items/${encodeURIComponent(itemId)}/search?${params}`));
  if (!r.ok) throw new Error(`Item search ${r.status}`);
  return r.json();
}

export async function fetchManifest(itemId) {
  const r = await fetch(serviceUrl(`/data/items/${itemId}/iiif/manifest.json`));
  if (!r.ok) throw new Error(`Manifest ${r.status}`);
  return r.json();
}

export async function fetchPageText(itemId, page) {
  const r = await fetch(serviceUrl(`/api/catalog/items/${encodeURIComponent(itemId)}/ocr/${encodeURIComponent(page)}?format=text`));
  return r.ok ? r.text() : "";
}

export function pageNumber(page) {
  return parseInt(String(page).replace("page-", ""), 10) || 1;
}

export function pageId(n) {
  return `page-${String(n).padStart(4, "0")}`;
}

async function adminJson(url, options) {
  const response = await fetch(serviceUrl(url), options);
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

export function fetchAdminQuality() {
  return adminJson("/api/admin/quality");
}

export function fetchAdminFixity() {
  return adminJson("/api/admin/fixity");
}

export function runAdminFixity() {
  return adminJson("/api/admin/fixity/run", { method: "POST" });
}

export function updateAdminItem(itemId, values) {
  return adminJson(`/api/admin/items/${encodeURIComponent(itemId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
}

export function fetchOcrWords(itemId, page) {
  return adminJson(`/api/admin/items/${encodeURIComponent(itemId)}/ocr/${encodeURIComponent(page)}/words`);
}

export function saveOcrCorrections(itemId, page, corrections, reviewer = "local administrator") {
  return adminJson(`/api/admin/items/${encodeURIComponent(itemId)}/ocr/${encodeURIComponent(page)}/corrections`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ corrections, reviewer }),
  });
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

export function scanAdminInbox() {
  return adminJson("/api/inbox?recursive=true");
}

export function fetchAdminBatches() {
  return adminJson("/api/batches");
}

export function createAdminBatch(files, processMode = "full") {
  return adminJson("/api/batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files, process_mode: processMode }),
  });
}

export function resumeAdminBatch(batchId) {
  return adminJson(`/api/batches/${encodeURIComponent(batchId)}/resume`, { method: "POST" });
}

export function cancelAdminBatch(batchId) {
  return adminJson(`/api/batches/${encodeURIComponent(batchId)}/cancel`, { method: "POST" });
}

export function deleteAdminBatch(batchId) {
  return adminJson(`/api/batches/${encodeURIComponent(batchId)}`, { method: "DELETE" });
}
