import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  cancelAdminJob,
  cancelAdminBatch,
  clearFinishedAdminJobs,
  createAdminBatch,
  deleteAdminBatch,
  analyzeBookMetadata,
  fetchAdminBatches,
  fetchAdminFixity,
  fetchAdminItems,
  fetchAdminJobs,
  fetchAdminQuality,
  fetchAdminTools,
  runItemAction,
  resumeAdminBatch,
  runAdminFixity,
  scanAdminInbox,
  uploadBook,
  updateAdminItem,
} from "../api.js";

const ACTIVE = new Set(["queued", "running", "canceling"]);

function StatusBadge({ status }) {
  return <span className={`status-badge status-${status}`}>{status}</span>;
}

function ToolStatus({ label, value, detail }) {
  return (
    <div className="tool-status">
      <span className={`health-dot ${value?.ok ? "healthy" : "unhealthy"}`} />
      <div>
        <strong>{label}</strong>
        <small>{detail || (value?.ok ? "Ready" : value?.error || "Unavailable")}</small>
      </div>
    </div>
  );
}

function formatTime(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatBytes(value = 0) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function confidenceLabel(value = 0) {
  if (value >= 0.8) return "High";
  if (value >= 0.55) return "Medium";
  if (value > 0) return "Low";
  return "Not found";
}

export default function AdminPage() {
  const [items, setItems] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [batches, setBatches] = useState([]);
  const [inbox, setInbox] = useState(null);
  const [scanningInbox, setScanningInbox] = useState(false);
  const [startingBatch, setStartingBatch] = useState(false);
  const [removingBatchId, setRemovingBatchId] = useState("");
  const [tools, setTools] = useState(null);
  const [quality, setQuality] = useState([]);
  const [fixity, setFixity] = useState(null);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [actionItem, setActionItem] = useState("");
  const [ocrLanguages, setOcrLanguages] = useState("ara+fas");
  const [selectedFile, setSelectedFile] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [editingItemId, setEditingItemId] = useState("");
  const [editValues, setEditValues] = useState(null);
  const [savingMetadata, setSavingMetadata] = useState(false);
  const uploadFormRef = useRef(null);

  const refresh = useCallback(async (includeTools = false) => {
    try {
      const requests = [fetchAdminItems(), fetchAdminJobs(), fetchAdminBatches()];
      if (includeTools) requests.push(fetchAdminQuality(), fetchAdminFixity(), fetchAdminTools());
      const [nextItems, nextJobs, nextBatches, nextQuality, nextFixity, nextTools] = await Promise.all(requests);
      setItems(nextItems);
      setJobs(nextJobs);
      setBatches(nextBatches);
      if (nextQuality) setQuality(nextQuality);
      if (nextFixity) setFixity(nextFixity);
      if (nextTools) setTools(nextTools);
      setSelectedJobId((current) => current || nextJobs[0]?.id || "");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    refresh(true);
    scanInbox();
    const timer = window.setInterval(() => refresh(false), 2500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function scanInbox() {
    setScanningInbox(true);
    setError("");
    try {
      setInbox(await scanAdminInbox());
    } catch (err) {
      setError(err.message);
    } finally {
      setScanningInbox(false);
    }
  }

  async function startInboxBatch() {
    const files = (inbox?.files || []).filter((file) => file.status !== "duplicate").map((file) => file.relative_path);
    if (!files.length) return;
    setStartingBatch(true);
    setError("");
    try {
      await createAdminBatch(files, "full");
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setStartingBatch(false);
    }
  }

  async function controlBatch(batchId, action) {
    setError("");
    try {
      if (action === "resume") await resumeAdminBatch(batchId);
      else await cancelAdminBatch(batchId);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function removeBatch(batchId) {
    const confirmed = window.confirm(
      "Remove this failed batch from the history? This will not delete the source PDF or any library books.",
    );
    if (!confirmed) return;
    setRemovingBatchId(batchId);
    setError("");
    try {
      await deleteAdminBatch(batchId);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setRemovingBatchId("");
    }
  }

  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) || jobs[0],
    [jobs, selectedJobId],
  );
  const hasActiveBatch = batches.some((batch) => ["queued", "running"].includes(batch.status));

  async function submitUpload(event) {
    event.preventDefault();
    const form = event.currentTarget;
    setUploading(true);
    setError("");
    try {
      const job = await uploadBook(new FormData(form));
      setSelectedJobId(job.id);
      form.reset();
      setOcrLanguages("ara+fas");
      setSelectedFile(null);
      setAnalysis(null);
      await refresh(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }

  function applyMetadata(result, overwrite = true) {
    const form = uploadFormRef.current;
    if (!form || !result) return;
    const values = {
      item_id: result.suggested_id,
      title: result.title,
      creator: result.creator,
      date_published: result.date_published,
      language: result.language,
      item_type: result.item_type,
      series_title: result.metadata?.series_title,
      collection_id: result.metadata?.collection_id,
      issue_number: result.metadata?.issue_number,
    };
    Object.entries(values).forEach(([name, value]) => {
      const field = form.elements.namedItem(name);
      if (field && value && (overwrite || !field.value)) field.value = value;
    });
  }

  async function analyzeSelectedBook() {
    if (!selectedFile) return;
    setAnalyzing(true);
    setAnalysis(null);
    setError("");
    try {
      const result = await analyzeBookMetadata(selectedFile);
      setAnalysis(result);
      applyMetadata(result, false);
    } catch (err) {
      setError(err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function runAction(itemId, action) {
    setActionItem(itemId);
    setError("");
    try {
      const job = await runItemAction(itemId, action, ocrLanguages);
      setSelectedJobId(job.id);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionItem("");
    }
  }

  async function cancelJob(jobId) {
    setError("");
    try {
      await cancelAdminJob(jobId);
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  async function clearFinishedJobs() {
    setError("");
    try {
      await clearFinishedAdminJobs();
      setSelectedJobId("");
      await refresh();
    } catch (err) {
      setError(err.message);
    }
  }

  function beginEdit(item) {
    setEditingItemId(item.id);
    setEditValues({
      title: item.title || "", creator: item.creator || "", publisher: item.publisher || "",
      place_published: item.place_published || "", date_published: item.date_published || "",
      date_calendar: item.date_calendar || "", series_title: item.series_title || "",
      collection_id: item.collection_id || "", volume_number: item.volume_number ?? "",
      issue_number: item.issue_number || "",
      cover_page: item.cover_page || 1, language: item.language || "fas", item_type: item.type || "book",
      rights: item.rights || "unknown", rights_basis: item.rights_basis || "",
      rights_reviewed_by: item.rights_reviewed_by || "local administrator", notes: item.notes || "",
      subjects: (item.subjects || []).join("\n"),
    });
  }

  async function saveMetadata(event) {
    event.preventDefault();
    setSavingMetadata(true); setError("");
    try {
      const payload = { ...editValues, subjects: editValues.subjects.split("\n").map((value) => value.trim()).filter(Boolean) };
      payload.volume_number = payload.volume_number === "" ? null : Number(payload.volume_number);
      payload.cover_page = Number(payload.cover_page || 1);
      await updateAdminItem(editingItemId, payload);
      setEditingItemId(""); setEditValues(null);
      await refresh();
    } catch (err) { setError(err.message); } finally { setSavingMetadata(false); }
  }

  async function startFixity() {
    setError("");
    try { await runAdminFixity(); await refresh(); } catch (err) { setError(err.message); }
  }

  return (
    <main className="admin-page">
      <section className="admin-heading">
        <div>
          <p className="eyebrow">Local administration</p>
          <h1>Library control room</h1>
          <p>Upload a PDF, follow each processing stage, and rerun individual tools when needed.</p>
        </div>
        <button className="secondary-button" onClick={() => refresh(true)}>Refresh status</button>
      </section>

      {error && <div className="admin-error">{error}</div>}

      <section className="admin-card inbox-card">
        <div className="section-heading">
          <div>
            <p className="step-number">Batch inbox</p>
            <h2>Process a folder automatically</h2>
            <p className="inbox-path">{inbox?.path || tools?.inbox?.path || "Checking the mounted inbox…"}</p>
          </div>
          <div className="inbox-actions">
            <button className="secondary-button" onClick={scanInbox} disabled={scanningInbox}>
              {scanningInbox ? "Scanning…" : "Scan folder"}
            </button>
            <button
              className="primary-button"
              onClick={startInboxBatch}
              disabled={startingBatch || hasActiveBatch || !(inbox?.files || []).some((file) => file.status !== "duplicate")}
            >
              {startingBatch ? "Starting…" : "Process new PDFs"}
            </button>
          </div>
        </div>

        {!inbox?.ok ? (
          <div className="empty-state">
            {inbox?.error || "Mount a folder with MEASTLIB_INBOX_DIR, then rebuild the Admin service."}
          </div>
        ) : (
          <div className="inbox-summary">
            <div className="inbox-facts">
              <span><strong>{inbox.files.length}</strong> PDFs</span>
              <span><strong>{formatBytes(inbox.total_bytes)}</strong> total</span>
              <span><strong>{inbox.files.filter((file) => file.status === "duplicate").length}</strong> duplicates</span>
            </div>
            <div className="inbox-files">
              {inbox.files.slice(0, 12).map((file) => (
                <div className="inbox-file" key={file.relative_path}>
                  <div>
                    <strong dir="auto">{file.relative_path}</strong>
                    <small>{formatBytes(file.bytes)} · {file.sha256.slice(0, 12)}</small>
                  </div>
                  <StatusBadge status={file.status} />
                </div>
              ))}
              {inbox.files.length > 12 && <small className="muted">And {inbox.files.length - 12} more files…</small>}
            </div>
          </div>
        )}

        {batches.slice(0, 3).map((batch) => {
          const completed = batch.files.filter((file) => ["succeeded", "duplicate"].includes(file.status)).length;
          const current = batch.files.find((file) => !["succeeded", "duplicate"].includes(file.status));
          return (
            <div className="batch-row" key={batch.id}>
              <div className="batch-summary">
                <StatusBadge status={batch.status} />
                <div>
                  <strong>{completed} / {batch.files.length} books complete</strong>
                  <small>
                    {current
                      ? `${current.relative_path} · ${current.stage}${current.pages_total ? ` · ${current.pages_done}/${current.pages_total} pages` : ""}`
                      : `Finished ${formatTime(batch.finished_at)}`}
                  </small>
                </div>
              </div>
              <div className="inbox-actions">
                {["partial", "failed", "canceled"].includes(batch.status) && (
                  <button className="secondary-button" onClick={() => controlBatch(batch.id, "resume")}>Resume</button>
                )}
                {["partial", "failed", "canceled"].includes(batch.status) && (
                  <button
                    className="danger-button"
                    disabled={removingBatchId === batch.id}
                    onClick={() => removeBatch(batch.id)}
                  >
                    {removingBatchId === batch.id ? "Removing…" : "Remove"}
                  </button>
                )}
                {["queued", "running"].includes(batch.status) && (
                  <button className="danger-button" onClick={() => controlBatch(batch.id, "cancel")}>Cancel</button>
                )}
              </div>
            </div>
          );
        })}
      </section>

      <div className="admin-grid">
        <section className="admin-card upload-card">
          <div className="section-heading">
            <div>
              <p className="step-number">01</p>
              <h2>Add an item</h2>
            </div>
            <span className="local-chip">PDF · up to 2 GB</span>
          </div>

          <form className="upload-form" onSubmit={submitUpload} ref={uploadFormRef}>
            <label className="file-picker">
              <span>PDF file</span>
              <input
                name="file"
                type="file"
                accept="application/pdf,.pdf"
                required
                onChange={(event) => {
                  setSelectedFile(event.target.files?.[0] || null);
                  setAnalysis(null);
                }}
              />
            </label>

            <div className="metadata-analyzer">
              <div>
                <strong>Automatic metadata</strong>
                <p>Reads this PDF locally and OCRs sampled opening and closing bibliographic pages. Nothing is sent to a cloud service.</p>
              </div>
              <button
                type="button"
                className="analyze-button"
                disabled={!selectedFile || analyzing}
                onClick={analyzeSelectedBook}
              >
                {analyzing ? "Analyzing pages…" : "Analyze and fill fields"}
              </button>
            </div>

            {analysis && (
              <div className="metadata-review">
                <div className="metadata-review-heading">
                  <div>
                    <strong>Suggestions ready</strong>
                    <small>{analysis.pages_analyzed} of {analysis.pages_total} pages examined</small>
                  </div>
                  <button type="button" className="secondary-button" onClick={() => applyMetadata(analysis, true)}>
                    Apply all again
                  </button>
                </div>
                <div className="suggestion-grid">
                  {[
                    ["Title", analysis.title, analysis.confidence?.title],
                    ["Creator", analysis.creator, analysis.confidence?.creator],
                    ["Date", analysis.date_published, analysis.confidence?.date_published],
                    ["Language", analysis.language, analysis.confidence?.language],
                    ["Type", analysis.item_type, analysis.confidence?.item_type],
                    ["Issue", analysis.metadata?.issue_number, analysis.confidence?.item_type],
                    ["Item ID", analysis.suggested_id, 0.7],
                  ].map(([label, value, confidence]) => (
                    <div className="suggestion" key={label}>
                      <span>{label}</span>
                      <strong>{value || "Not found"}</strong>
                      <small className={`confidence confidence-${confidenceLabel(confidence).toLowerCase().replace(" ", "-")}`}>
                        {confidenceLabel(confidence)} confidence
                      </small>
                    </div>
                  ))}
                </div>
                <details className="metadata-evidence">
                  <summary>Why these values were suggested</summary>
                  <ul>
                    {(analysis.evidence || []).map((item, index) => (
                      <li key={`${item.field}-${index}`}>
                        <strong>{item.field}</strong>: {item.source}
                        {item.page ? `, page ${item.page}` : ""}
                        {item.text ? ` — ${item.text}` : ""}
                      </li>
                    ))}
                  </ul>
                </details>
                {(analysis.warnings || []).map((warning) => <p className="analysis-warning" key={warning}>{warning}</p>)}
              </div>
            )}

            <div className="form-row">
              <label>
                Permanent item ID
                <input name="item_id" placeholder="book-title-1924" pattern="[a-z0-9][a-z0-9._-]*" required />
                <small>Lowercase, URL-safe, and never reused.</small>
              </label>
              <label>
                Title
                <input name="title" placeholder="Book title" required />
              </label>
            </div>

            <div className="form-row three-fields newspaper-fields">
              <label>
                Publication / series
                <input name="series_title" placeholder="کیهان" />
              </label>
              <label>
                Collection ID
                <input name="collection_id" placeholder="newspaper-kayhan" pattern="[a-z0-9][a-z0-9._-]*" />
              </label>
              <label>
                Issue number
                <input name="issue_number" placeholder="10632" />
              </label>
            </div>

            <div className="form-row">
              <label>
                Creator
                <input name="creator" placeholder="Author or editor" />
              </label>
              <label>
                Publication date
                <input name="date_published" placeholder="1924 or 1924-05-01" />
              </label>
            </div>

            <div className="form-row three-fields">
              <label>
                Language
                <select name="language" defaultValue="ara">
                  <option value="ara">Arabic</option>
                  <option value="fas">Persian</option>
                  <option value="ota">Ottoman Turkish</option>
                  <option value="urd">Urdu</option>
                </select>
              </label>
              <label>
                Type
                <select name="item_type" defaultValue="book">
                  <option value="book">Book</option>
                  <option value="newspaper">Newspaper</option>
                  <option value="document">Document</option>
                </select>
              </label>
              <label>
                Rights
                <select name="rights" defaultValue="unknown">
                  <option value="unknown">Unknown / private</option>
                  <option value="public-domain">Public domain</option>
                  <option value="in-copyright">In copyright</option>
                </select>
              </label>
            </div>

            <div className="form-row">
              <label>
                Processing
                <select name="process_mode" defaultValue="full">
                  <option value="full">Full — OCR, viewer, and search</option>
                  <option value="viewer">Viewer only — skip OCR and search</option>
                </select>
              </label>
              <label>
                OCR language packs
                <input
                  name="ocr_languages"
                  value={ocrLanguages}
                  onChange={(event) => setOcrLanguages(event.target.value)}
                  placeholder="ara+fas"
                />
              </label>
            </div>

            <label>
              Source note
              <input name="source_note" placeholder="Collection, donor, or source URL" />
            </label>

            <button className="primary-button" disabled={uploading}>
              {uploading ? "Uploading…" : "Upload and start processing"}
            </button>
            <p className="form-note">For newspapers, keep one PDF per issue and use the same collection ID for the complete publication run. Only mark an item public domain after checking its rights.</p>
          </form>
        </section>

        <aside className="admin-card tools-card">
          <div className="section-heading">
            <div>
              <p className="step-number">System</p>
              <h2>Tools & services</h2>
            </div>
          </div>
          {!tools ? <p className="muted">Checking tools…</p> : (
            <div className="tools-list">
              <ToolStatus
                label="Tesseract OCR"
                value={tools.tesseract}
                detail={tools.tesseract?.ok
                  ? `${tools.tesseract.version} · ${(tools.tesseract.languages || []).join(", ")}`
                  : "Unavailable"}
              />
              <ToolStatus label="Solr search" value={tools.solr} />
              <ToolStatus label="IIIF images" value={tools.iiif} />
              <ToolStatus label="Library storage" value={tools.storage} detail={tools.storage?.path} />
              <ToolStatus label="Batch inbox" value={tools.inbox} detail={tools.inbox?.path} />
              <ToolStatus label="Metadata analyzer" value={tools.metadata} detail={tools.metadata?.detail} />
            </div>
          )}
          <div className="queue-note">
            <strong>One processing job at a time</strong>
            <p>This keeps OCR predictable on a laptop. Additional uploads wait safely in the queue.</p>
          </div>
          <div className="security-note">
            <strong>Local access only</strong>
            <p>This dashboard has no login yet. Do not expose it directly to the public internet.</p>
          </div>
        </aside>
      </div>

      <section className="admin-card quality-card">
        <div className="section-heading"><div><p className="step-number">Review</p><h2>Quality & rights queue</h2><p className={`fixity-summary ${fixity?.ok === false ? "failed" : ""}`}>{fixity?.ok == null ? "Fixity has not been checked." : fixity.ok ? `Fixity verified for ${fixity.items?.length || 0} items.` : "Fixity failures require attention."}</p></div><div className="inbox-actions"><span className="item-count">{quality.length} item{quality.length === 1 ? "" : "s"}</span><button className="secondary-button" onClick={startFixity}>Run fixity audit</button></div></div>
        {quality.length === 0 ? <div className="empty-state">No catalog, OCR, rights, or index exceptions.</div> : <div className="quality-list">{quality.slice(0, 20).map((entry) => <div className="quality-row" key={entry.item.id}><div><strong dir="auto">{entry.item.title}</strong><small>{entry.item.id}</small></div><div className="quality-issues">{entry.issues.map((issue) => <span key={issue}>{issue.replaceAll("-", " ")}</span>)}</div><div><small>{entry.low_pages.length ? `${entry.low_pages.length} low-confidence pages` : ""}</small><button className="secondary-button" onClick={() => beginEdit(entry.summary)}>Review metadata</button>{entry.low_pages[0] && <Link className="secondary-button" to={`/admin/correct/${entry.item.id}/${entry.low_pages[0].page}`}>Correct OCR</Link>}</div></div>)}</div>}
      </section>

      {editingItemId && editValues && <section className="admin-card metadata-editor">
        <div className="section-heading"><div><p className="step-number">Catalog record</p><h2>Edit {editingItemId}</h2></div><button className="secondary-button" onClick={() => { setEditingItemId(""); setEditValues(null); }}>Close</button></div>
        <form className="upload-form" onSubmit={saveMetadata}>
          <div className="form-row"><label>Title<input dir="auto" value={editValues.title} onChange={(e) => setEditValues({ ...editValues, title: e.target.value })} required /></label><label>Creator<input dir="auto" value={editValues.creator} onChange={(e) => setEditValues({ ...editValues, creator: e.target.value })} /></label></div>
          <div className="form-row three-fields"><label>Publisher<input dir="auto" value={editValues.publisher} onChange={(e) => setEditValues({ ...editValues, publisher: e.target.value })} /></label><label>Place published<input dir="auto" value={editValues.place_published} onChange={(e) => setEditValues({ ...editValues, place_published: e.target.value })} /></label><label>Publication date<input value={editValues.date_published} onChange={(e) => setEditValues({ ...editValues, date_published: e.target.value })} /></label></div>
          <div className="form-row three-fields"><label>Publication / series<input dir="auto" value={editValues.series_title} onChange={(e) => setEditValues({ ...editValues, series_title: e.target.value })} /></label><label>Collection ID<input value={editValues.collection_id} onChange={(e) => setEditValues({ ...editValues, collection_id: e.target.value })} /></label><label>Issue number<input value={editValues.issue_number} onChange={(e) => setEditValues({ ...editValues, issue_number: e.target.value })} /></label></div>
          <label>Volume number<input type="number" min="1" value={editValues.volume_number} onChange={(e) => setEditValues({ ...editValues, volume_number: e.target.value })} /></label>
          <div className="form-row three-fields"><label>Language<select value={editValues.language} onChange={(e) => setEditValues({ ...editValues, language: e.target.value })}><option value="ara">Arabic</option><option value="fas">Persian</option><option value="ota">Ottoman Turkish</option><option value="urd">Urdu</option></select></label><label>Type<select value={editValues.item_type} onChange={(e) => setEditValues({ ...editValues, item_type: e.target.value })}><option value="book">Book</option><option value="newspaper">Newspaper</option><option value="document">Document</option></select></label><label>Cover page<input type="number" min="1" value={editValues.cover_page} onChange={(e) => setEditValues({ ...editValues, cover_page: e.target.value })} /></label></div>
          <label>Subjects, one per line<textarea dir="auto" rows="4" value={editValues.subjects} onChange={(e) => setEditValues({ ...editValues, subjects: e.target.value })} /></label>
          <div className="rights-review"><div className="form-row"><label>Rights<select value={editValues.rights} onChange={(e) => setEditValues({ ...editValues, rights: e.target.value })}><option value="unknown">Unknown / private</option><option value="public-domain">Public domain</option><option value="in-copyright">In copyright</option></select></label><label>Reviewed by<input value={editValues.rights_reviewed_by} onChange={(e) => setEditValues({ ...editValues, rights_reviewed_by: e.target.value })} /></label></div><label>Rights basis<textarea rows="3" value={editValues.rights_basis} onChange={(e) => setEditValues({ ...editValues, rights_basis: e.target.value })} placeholder="Citation or reasoning supporting the determination" /></label><p>Public access is enabled only when “Public domain” has a recorded basis and review.</p></div>
          <label>Catalog notes<textarea rows="3" value={editValues.notes} onChange={(e) => setEditValues({ ...editValues, notes: e.target.value })} /></label>
          <button className="primary-button" disabled={savingMetadata}>{savingMetadata ? "Saving…" : "Save and rebuild catalog outputs"}</button>
        </form>
      </section>}

      <section className="admin-card library-card">
        <div className="section-heading">
          <div>
            <p className="step-number">02</p>
            <h2>Library items</h2>
          </div>
          <span className="item-count">{items.length} item{items.length === 1 ? "" : "s"}</span>
        </div>

        {items.length === 0 ? (
          <div className="empty-state">No books yet. Upload the first PDF above.</div>
        ) : (
          <div className="item-table-wrap">
            <table className="item-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Progress</th>
                  <th>Rights</th>
                  <th>Tools</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.title || item.id}</strong>
                      <small>{item.creator ? `${item.creator} · ` : ""}{item.id}</small>
                    </td>
                    <td>
                      <div className="progress-facts">
                        <span>{item.access_pages} pages</span>
                        <span className={item.ocr_pages ? "complete-fact" : ""}>{item.ocr_pages} OCR</span>
                        {item.ocr_confidence != null && <span>{Math.round(item.ocr_confidence * 100)}% confidence</span>}
                        <span className={item.has_manifest ? "complete-fact" : ""}>
                          {item.has_manifest ? "Viewer ready" : "No viewer"}
                        </span>
                        <span className={item.searchable_pdf ? "complete-fact" : ""}>
                          {item.searchable_pdf ? "PDF searchable" : "No searchable PDF"}
                        </span>
                        <span className={item.indexed_pages ? "complete-fact" : ""}>
                          {item.indexed_pages ?? "—"} indexed
                        </span>
                      </div>
                    </td>
                    <td><span className="rights-label">{item.rights || "unknown"}</span></td>
                    <td>
                      <div className="action-menu">
                        {item.has_manifest && <Link to={`/item/${item.id}/1`}>Open</Link>}
                        <button disabled={actionItem === item.id} onClick={() => beginEdit(item)}>Edit</button>
                        <button disabled={actionItem === item.id} onClick={() => runAction(item.id, "ocr")}>OCR</button>
                        <button disabled={actionItem === item.id} onClick={() => runAction(item.id, "manifest")}>Viewer</button>
                        <button disabled={actionItem === item.id} onClick={() => runAction(item.id, "index")}>Index</button>
                        <button disabled={actionItem === item.id} onClick={() => runAction(item.id, "all")}>Run all</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="jobs-grid">
        <section className="admin-card jobs-card">
          <div className="section-heading">
            <div>
              <p className="step-number">03</p>
              <h2>Processing queue</h2>
            </div>
            {jobs.some((job) => !ACTIVE.has(job.status)) && (
              <button className="text-button" onClick={clearFinishedJobs}>Clear finished</button>
            )}
          </div>
          {jobs.length === 0 ? <div className="empty-state">No processing jobs yet.</div> : (
            <div className="job-list">
              {jobs.map((job) => (
                <button
                  key={job.id}
                  className={`job-row ${selectedJob?.id === job.id ? "selected" : ""}`}
                  onClick={() => setSelectedJobId(job.id)}
                >
                  <div>
                    <strong>{job.item_id}</strong>
                    <small>{job.stage} · {formatTime(job.created_at)}</small>
                  </div>
                  <StatusBadge status={job.status} />
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="admin-card log-card">
          <div className="section-heading">
            <div>
              <p className="step-number">Live output</p>
              <h2>{selectedJob ? selectedJob.item_id : "Job log"}</h2>
            </div>
            {selectedJob && ACTIVE.has(selectedJob.status) && (
              <button className="danger-button" onClick={() => cancelJob(selectedJob.id)}>Cancel job</button>
            )}
          </div>
          {selectedJob ? (
            <>
              <div className="log-summary">
                <StatusBadge status={selectedJob.status} />
                <span>{selectedJob.stage}</span>
                {selectedJob.error && <span className="log-error">{selectedJob.error}</span>}
              </div>
              <pre className="job-log">{selectedJob.logs?.join("\n") || "Waiting for output…"}</pre>
            </>
          ) : <div className="empty-state">Select a job to inspect its output.</div>}
        </section>
      </div>
    </main>
  );
}
