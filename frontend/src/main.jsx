import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./styles.css";

function Layout({ children }) {
  return (
    <div className="app-shell">
      <header>
        <strong>Missing Person Detection</strong>
        <nav>
          <a href="/">Dashboard</a>
          <a href="/cases">Cases</a>
        </nav>
      </header>
      <main>{children}</main>
    </div>
  );
}

function Dashboard() {
  return (
    <section>
      <p className="eyebrow">Operations dashboard</p>
      <h1>Welcome</h1>
      <p>The detection and review workspace will be available here.</p>
    </section>
  );
}

function Cases() {
  return (
    <section>
      <p className="eyebrow">Case management</p>
      <h1>Missing-person cases</h1>
      <p>Case registration and search workflows are planned for a later phase.</p>
    </section>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/cases" element={<Cases />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  </React.StrictMode>,
);
