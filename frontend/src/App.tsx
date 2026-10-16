import { NavLink, Route, Routes } from "react-router-dom";
import { useSession } from "./lib/session";
import { AccountPage } from "./pages/Account";
import { DraftsPage } from "./pages/Drafts";
import { LowConfidencePage } from "./pages/LowConfidence";
import { QueuePage } from "./pages/Queue";
import { RunsPage } from "./pages/Runs";

function SessionBar() {
  const { session, setSession } = useSession();
  return (
    <div className="session">
      <label>Tenant id <input value={session.tenantId} onChange={(e) => setSession({ ...session, tenantId: e.target.value.trim() })} /></label>
      <label>User id <input value={session.userId ?? ""} onChange={(e) => setSession({ ...session, userId: e.target.value.trim() || undefined })} /></label>
    </div>
  );
}

export default function App() {
  const { session } = useSession();
  return (
    <>
      <header className="top">
        <strong>Pulse</strong>
        <nav>
          <NavLink to="/">Queue</NavLink>
          <NavLink to="/low-confidence">Low confidence</NavLink>
          <NavLink to="/drafts">Drafts</NavLink>
          <NavLink to="/runs">Run log</NavLink>
        </nav>
        <SessionBar />
      </header>
      <main>
        {!session.tenantId ? <p className="warn">Enter a tenant id above to begin.</p> : (
          <Routes>
            <Route path="/" element={<QueuePage />} />
            <Route path="/low-confidence" element={<LowConfidencePage />} />
            <Route path="/accounts/:id" element={<AccountPage />} />
            <Route path="/drafts" element={<DraftsPage />} />
            <Route path="/runs" element={<RunsPage />} />
          </Routes>
        )}
      </main>
    </>
  );
}
