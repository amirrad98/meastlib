import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchOcrWords, saveOcrCorrections } from "../api.js";

export default function CorrectionPage() {
  const { itemId, page } = useParams();
  const [data, setData] = useState(null);
  const [values, setValues] = useState({});
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState("");
  useEffect(() => {
    fetchOcrWords(itemId, page).then((value) => {
      setData(value);
      setValues(Object.fromEntries(value.words.map((word) => [word.id, word.corrected || word.content])));
    }).catch((e) => setError(e.message));
  }, [itemId, page]);
  const changed = useMemo(() => data ? data.words.filter((word) => (values[word.id] ?? word.content).trim() !== word.content) : [], [data, values]);
  async function save(event) {
    event.preventDefault(); setSaving(true); setError(""); setSaved("");
    try {
      await saveOcrCorrections(itemId, page, changed.map((word) => ({ word_id: word.id, original: word.content, content: values[word.id] })));
      setSaved("Corrections saved and reindexing queued. The existing searchable PDF is marked for regeneration.");
      const refreshed = await fetchOcrWords(itemId, page); setData(refreshed);
    } catch (e) { setError(e.message); } finally { setSaving(false); }
  }
  return <main className="admin-page correction-page"><div className="admin-heading"><div><p className="eyebrow">OCR correction</p><h1>{itemId} · {page}</h1><p>Edit individual recognized words. The original ALTO remains preserved.</p></div><Link className="secondary-button" to="/admin">Back to control room</Link></div>{error && <div className="admin-error">{error}</div>}{saved && <div className="success-note">{saved}</div>}{!data ? <p>Loading words…</p> : <form onSubmit={save}><div className="correction-layout"><div className="correction-image"><img src={data.image} alt={`Scanned ${page}`} /></div><section className="admin-card correction-words"><div className="section-heading"><div><p className="step-number">Word-level review</p><h2>{data.words.length} words</h2></div><span className="item-count">{changed.length} changed</span></div><div className="word-grid">{data.words.map((word) => <label className={word.confidence < .7 ? "low-confidence" : ""} key={word.id}><span>{word.id} · {Math.round(word.confidence * 100)}%</span><input dir="auto" value={values[word.id] ?? word.content} onChange={(e) => setValues({ ...values, [word.id]: e.target.value })} /></label>)}</div></section></div><button className="primary-button correction-save" disabled={saving || !changed.length}>{saving ? "Saving…" : `Save ${changed.length} correction${changed.length === 1 ? "" : "s"}`}</button></form>}</main>;
}
