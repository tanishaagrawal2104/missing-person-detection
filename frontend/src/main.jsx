import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import {
  BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useParams,
} from "react-router-dom";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
const auth = {
  get token() { return localStorage.getItem("access_token"); },
  save(data) { localStorage.setItem("access_token", data.access_token); localStorage.setItem("user", JSON.stringify(data.user)); },
  clear() { localStorage.removeItem("access_token"); localStorage.removeItem("user"); },
};

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function Protected({ children }) {
  return auth.token ? children : <Navigate to="/login" replace />;
}

function Layout({ children }) {
  const navigate = useNavigate();
  const logout = () => { auth.clear(); navigate("/login"); };
  return <div className="app-shell">
    <header><Link className="brand" to="/">Missing Person Detection</Link>
      <nav><Link to="/sighting">Public Sighting</Link>{auth.token && <><Link to="/">Dashboard</Link><Link to="/cases">Cases</Link><button onClick={logout}>Log out</button></>}</nav>
    </header><main>{children}</main>
  </div>;
}

function ReferenceThumbnail({ imageId }) {
  const [url, setUrl] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    fetch(`${API}/api/images/${imageId}`, {
      headers: { Authorization: `Bearer ${auth.token}` },
    }).then((response) => {
      if (!response.ok) throw new Error("Reference image unavailable");
      return response.blob();
    }).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (active) setUrl(objectUrl);
    }).catch(() => {});
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [imageId]);

  return url ? <img className="candidate-thumbnail" src={url} alt="Reference face" /> : <span>Reference image unavailable</span>;
}

function AuthPage({ register = false }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault(); setError("");
    try { const data = await request(`/api/auth/${register ? "register" : "login"}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) }); auth.save(data); navigate("/"); }
    catch (err) { setError(err.message); }
  };
  return <section className="card narrow"><h1>{register ? "Create account" : "Sign in"}</h1>
    <form onSubmit={submit}><label>Email<input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
      <label>Password<input type="password" minLength="12" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
      {error && <p className="error">{error}</p>}<button className="primary">{register ? "Register" : "Sign in"}</button>
    </form><p><Link to={register ? "/login" : "/register"}>{register ? "Already registered? Sign in" : "Need an account? Register"}</Link></p>
  </section>;
}

function Dashboard() {
  const [data, setData] = useState(null); const [mapRecords, setMapRecords] = useState([]); const [error, setError] = useState("");
  useEffect(() => { Promise.all([request("/api/dashboard"), request("/api/dashboard/map")]).then(([summary, records]) => { setData(summary); setMapRecords(records); }).catch((e) => setError(e.message)); }, []);
  if (error) return <p className="error">{error}</p>; if (!data) return <p>Loading dashboard...</p>;
  return <><p className="eyebrow">Operations dashboard</p><h1>Overview</h1>
    <div className="stats">{[["Total cases", data.total_cases], ["Open", data.open_cases], ["Under review", data.under_review_cases], ["Resolved", data.resolved_cases]].map(([label, value]) => <div className="card stat" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
    <section className="card"><h2>India map</h2><p>Only saved coordinates are shown. Records without coordinates are omitted.</p><MapContainer className="map" center={[22.5, 79]} zoom={4} scrollWheelZoom><TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />{mapRecords.map((record) => <CircleMarker key={`${record.record_type}-${record.id}`} center={[record.latitude, record.longitude]} pathOptions={{ color: record.record_type === "case" ? "#536dfe" : "#e67e22" }}><Popup><strong>{record.label}</strong><br />{record.record_type} · {record.status}{record.observed_at && <><br />{new Date(record.observed_at).toLocaleString()}</>}</Popup></CircleMarker>)}</MapContainer></section>
    <section className="card"><h2>Recent activity</h2>{data.recent_activity.length ? data.recent_activity.map((item) => <p key={item.id}><Link to={`/cases/${item.id}`}>{item.name}</Link> · {item.status}</p>) : <p>No cases yet.</p>}</section>
    <AdminImport />
  </>;
}

function AdminImport() {
  const user = JSON.parse(localStorage.getItem("user") || "null"); const [file, setFile] = useState(null); const [message, setMessage] = useState(""); const [error, setError] = useState(""); const [smtp, setSmtp] = useState(null);
  useEffect(() => { request("/api/admin/notification-status").then((status) => setSmtp(status.smtp_configured)).catch(() => {}); }, []);
  if (user?.role !== "admin") return null;
  const submit = async (e) => { e.preventDefault(); const data = new FormData(); data.append("file", file); try { const result = await request("/api/admin/demo-import", { method: "POST", body: data }); setMessage(`Imported ${result.imported_cases} cases and ${result.imported_sightings} sightings.`); setError(result.errors?.join("; ") || ""); } catch (err) { setError(err.message); } };
  return <section className="card"><h2>Import synthetic demo data</h2><p>Administrator-only. CSV rows must be synthetic sample records; no facial representations are imported.</p><p>Email notifications: {smtp === null ? "checking configuration..." : smtp ? "configured" : "not configured"}</p><form onSubmit={submit}><input type="file" accept=".csv,text/csv" required onChange={(e) => setFile(e.target.files[0])} /><button className="primary">Import CSV</button></form>{message && <p className="success">{message}</p>}{error && <p className="error">{error}</p>}</section>;
}

function Cases() {
  const [cases, setCases] = useState([]); const [search, setSearch] = useState(""); const [error, setError] = useState("");
  const load = () => request(`/api/cases?search=${encodeURIComponent(search)}`).then(setCases).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  return <><div className="row"><div><p className="eyebrow">Case management</p><h1>Cases</h1></div><Link className="button primary" to="/cases/new">New case</Link></div>
    <form className="search" onSubmit={(e) => { e.preventDefault(); load(); }}><input placeholder="Search cases" value={search} onChange={(e) => setSearch(e.target.value)} /><button>Search</button></form>
    {error && <p className="error">{error}</p>}<div className="list">{cases.map((item) => <Link className="card" to={`/cases/${item.id}`} key={item.id}><h2>{item.name}</h2><p>{item.last_seen_location || "Location not provided"} · {item.status}</p></Link>)}{!cases.length && <p>No cases found.</p>}</div>
  </>;
}

function CaseForm() {
  const navigate = useNavigate(); const [form, setForm] = useState({ name: "", description: "", last_seen_location: "", last_seen_at: "", last_seen_latitude: "", last_seen_longitude: "" }); const [error, setError] = useState("");
  const submit = async (e) => { e.preventDefault(); try { const item = await request("/api/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, last_seen_at: form.last_seen_at || null, last_seen_latitude: form.last_seen_latitude === "" ? null : Number(form.last_seen_latitude), last_seen_longitude: form.last_seen_longitude === "" ? null : Number(form.last_seen_longitude) }) }); navigate(`/cases/${item.id}`); } catch (err) { setError(err.message); } };
  return <section className="card"><h1>New missing-person case</h1><form onSubmit={submit}><label>Name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label>Description<textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label><label>Last-seen location<input value={form.last_seen_location} onChange={(e) => setForm({ ...form, last_seen_location: e.target.value })} /></label><label>Last-seen time<input type="datetime-local" value={form.last_seen_at} onChange={(e) => setForm({ ...form, last_seen_at: e.target.value })} /></label><label>Last-seen latitude<input type="number" step="any" min="-90" max="90" value={form.last_seen_latitude} onChange={(e) => setForm({ ...form, last_seen_latitude: e.target.value })} /></label><label>Last-seen longitude<input type="number" step="any" min="-180" max="180" value={form.last_seen_longitude} onChange={(e) => setForm({ ...form, last_seen_longitude: e.target.value })} /></label>{error && <p className="error">{error}</p>}<button className="primary">Create case</button></form></section>;
}

function CaseDetail() {
  const { id } = useParams(); const [item, setItem] = useState(null); const [error, setError] = useState(""); const [image, setImage] = useState(null); const [searchFile, setSearchFile] = useState(null); const [jobs, setJobs] = useState([]); const [sightings, setSightings] = useState([]); const [message, setMessage] = useState(""); const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => { request(`/api/cases/${id}`).then(setItem).catch((e) => setError(e.message)); }, [id]);
  useEffect(() => {
    let stopped = false;
    let timer;
    const load = async () => {
      try {
        const items = await request("/api/search-jobs");
        if (stopped) return;
        const caseJobs = items.filter((job) => job.case_id === id);
        setJobs(caseJobs);
        if (caseJobs.some((job) => job.status === "queued" || job.status === "processing")) {
          timer = setTimeout(load, 1500);
        }
      } catch (e) {
        if (!stopped) setError(e.message);
      }
    };
    load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id, refreshKey]);
  useEffect(() => { request("/api/sightings").then((items) => setSightings(items.filter((sighting) => sighting.case_id === id))).catch(() => {}); }, [id]);
  const upload = async (e) => { e.preventDefault(); const data = new FormData(); data.append("image", image); try { await request(`/api/cases/${id}/images`, { method: "POST", body: data }); setMessage("Reference image uploaded."); } catch (err) { setError(err.message); } };
  const search = async (e, type) => { e.preventDefault(); const data = new FormData(); data.append(type, searchFile); try { const job = await request(`/api/cases/${id}/search/${type}`, { method: "POST", body: data }); setJobs([job, ...jobs]); setRefreshKey((value) => value + 1); setMessage(`${type} search queued. Results require human verification.`); } catch (err) { setError(err.message); } };
  const review = async (candidateId, status) => { try { const updated = await request(`/api/candidate-matches/${candidateId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }); setJobs((current) => current.map((job) => ({ ...job, candidates: job.candidates?.map((candidate) => candidate.id === updated.id ? updated : candidate) }))); setMessage("Candidate review saved."); } catch (err) { setError(err.message); } };
  const reviewSighting = async (sightingId, status) => { try { const updated = await request(`/api/sightings/${sightingId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }); setSightings(sightings.map((sighting) => sighting.id === updated.id ? updated : sighting)); setMessage("Sighting review saved."); } catch (err) { setError(err.message); } };
  if (error) return <p className="error">{error}</p>; if (!item) return <p>Loading case...</p>;
  return <section><p className="eyebrow">Case details</p><h1>{item.name}</h1><div className="card"><p>{item.description || "No description provided."}</p><p><strong>Status:</strong> {item.status}</p><p><strong>Last seen:</strong> {item.last_seen_location || "Not provided"}</p><h2>Reference photographs</h2><form onSubmit={upload}><input type="file" accept="image/jpeg,image/png,image/webp" required onChange={(e) => setImage(e.target.files[0])} /><button>Upload image</button></form><h2>AI search</h2><p>Results are possible matches only and require human verification.</p><form onSubmit={(e) => search(e, "image")}><input type="file" accept="image/jpeg,image/png,image/webp" required onChange={(e) => setSearchFile(e.target.files[0])} /><button>Search image</button></form><form onSubmit={(e) => search(e, "video")}><input type="file" accept="video/mp4,video/webm,video/quicktime" required onChange={(e) => setSearchFile(e.target.files[0])} /><button>Search video</button></form>{message && <p className="success">{message}</p>}</div><div className="card"><h2>Reported sightings</h2>{sightings.length ? sightings.map((sighting) => <p key={sighting.id}>{sighting.observed_at ? new Date(sighting.observed_at).toLocaleString() : "Time unavailable"} · {sighting.location || "Location unavailable"} · {sighting.status} <button onClick={() => reviewSighting(sighting.id, "under_review")}>Review</button> <button onClick={() => reviewSighting(sighting.id, "verified")}>Verify</button> <button onClick={() => reviewSighting(sighting.id, "rejected")}>Reject</button></p>) : <p>No sightings submitted.</p>}</div><div className="card"><h2>Search history</h2>{jobs.map((job) => <div key={job.id}><p>{job.job_type} · {job.status} · {job.progress}%</p>{job.error_message && <p className="error">{job.error_message}</p>}{job.status === "completed" && (job.candidates?.length ? <div><h3>Candidate matches</h3>{job.candidates.map((candidate) => <div className="candidate-match" key={candidate.id}><div>{candidate.reference_image_id ? <ReferenceThumbnail imageId={candidate.reference_image_id} /> : <span>Reference image unavailable</span>}</div><div><strong>{job.case_name}</strong><p>Case ID: {job.case_id}</p><p>Similarity distance: {candidate.distance?.toFixed(3) ?? "Unavailable"}</p>{candidate.frame_timestamp_seconds != null && <p>Video timestamp: {candidate.frame_timestamp_seconds.toFixed(1)}s</p>}<p>Status: {candidate.status}</p><button onClick={() => review(candidate.id, "under_review")}>Review</button> <button onClick={() => review(candidate.id, "possible_match")}>Possible match</button> <button onClick={() => review(candidate.id, "not_a_match")}>Not a match</button></div></div>)}</div> : <p>No candidate matches were found for this search.</p>)}</div>)}</div></section>;
}

function PublicSighting() {
  const [form, setForm] = useState({ case_id: "", observed_at: "", location: "", latitude: "", longitude: "", description: "" }); const [image, setImage] = useState(null); const [message, setMessage] = useState(""); const [error, setError] = useState("");
  const submit = async (e) => { e.preventDefault(); const data = new FormData(); Object.entries(form).forEach(([key, value]) => data.append(key, value)); data.append("image", image); try { const result = await request("/api/public/sightings", { method: "POST", body: data }); setMessage(result.message); } catch (err) { setError(err.message); } };
  return <section className="card"><p className="eyebrow">Public portal</p><h1>Submit a possible sighting</h1><p>Only submit information you are authorized to share. Case records remain private.</p><form onSubmit={submit}><label>Case ID<input required value={form.case_id} onChange={(e) => setForm({ ...form, case_id: e.target.value })} /></label><label>Observation time<input type="datetime-local" required value={form.observed_at} onChange={(e) => setForm({ ...form, observed_at: e.target.value })} /></label><label>Location<input required value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></label><label>Latitude<input type="number" step="any" min="-90" max="90" value={form.latitude} onChange={(e) => setForm({ ...form, latitude: e.target.value })} /></label><label>Longitude<input type="number" step="any" min="-180" max="180" value={form.longitude} onChange={(e) => setForm({ ...form, longitude: e.target.value })} /></label><label>Description<textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label><label>Photograph<input type="file" accept="image/jpeg,image/png,image/webp" required onChange={(e) => setImage(e.target.files[0])} /></label>{error && <p className="error">{error}</p>}{message && <p className="success">{message}</p>}<button className="primary">Submit sighting</button></form></section>;
}

function App() {
  return <Layout><Routes><Route path="/login" element={<AuthPage />} /><Route path="/register" element={<AuthPage register />} /><Route path="/sighting" element={<PublicSighting />} /><Route path="/" element={<Protected><Dashboard /></Protected>} /><Route path="/cases" element={<Protected><Cases /></Protected>} /><Route path="/cases/new" element={<Protected><CaseForm /></Protected>} /><Route path="/cases/:id" element={<Protected><CaseDetail /></Protected>} /><Route path="*" element={<Navigate to="/" replace />} /></Routes></Layout>;
}

ReactDOM.createRoot(document.getElementById("root")).render(<React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>);
