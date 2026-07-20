import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  cancelAdminJob,
  clearFinishedAdminJobs,
  analyzeBookMetadata,
  fetchAdminItems,
  fetchAdminJobs,
  fetchAdminTools,
  runItemAction,
  uploadBook,
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

function confidenceLabel(value = 0) {
  if (value >= 0.8) return "High";
  if (value >= 0.55) return "Medium";
  if (value > 0) return "Low";
  return "Not found";
}

export default function AdminPage() {
  const [items, setItems] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [tools, setTools] = useState(null);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [actionItem, setActionItem] = useState("");
  const [ocrLanguages, setOcrLanguages] = useState("ara+fas");
  const [selectedFile, setSelectedFile] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const uploadFormRef = useRef(null);

  const refresh = useCallback(async (includeTools = false) => {
    try {
      const requests = [fetchAdminItems(), fetchAdminJobs()];
      if (includeTools) requests.push(fetchAdminTools());
      const [nextItems, nextJobs, nextTools] = await Promise.all(requests);
      setItems(nextItems);
      setJobs(nextJobs);
      if (nextTools) setTools(nextTools);
      setSelectedJobId((current) => current || nextJobs[0]?.id || "");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    refresh(true);
    const timer = window.setInterval(() => refresh(false), 2500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) || jobs[0],
    [jobs, selectedJobId],
  );

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

      <div className="admin-grid">
        <section className="admin-card upload-card">
          <div className="section-heading">
            <div>
              <p className="step-number">01</p>
              <h2>Add a book</h2>
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
                <p>Reads this PDF locally and OCRs up to four scanned opening pages. Nothing is sent to a cloud service.</p>
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
            <p className="form-note">Only mark a book public domain after checking its rights.</p>
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
                        <span className={item.has_manifest ? "complete-fact" : ""}>
                          {item.has_manifest ? "Viewer ready" : "No viewer"}
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
