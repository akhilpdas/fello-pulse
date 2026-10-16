import { NavLink, Route, Routes } from "react-router-dom";
import { useSession } from "./lib/session";
import { navFor } from "./lib/nav";
import { AccountPage } from "./pages/Account";
import { AdminPage } from "./pages/Admin";
import { DraftsPage } from "./pages/Drafts";
import { LoginPage } from "./pages/Login";
import { LowConfidencePage } from "./pages/LowConfidence";
import { QueuePage } from "./pages/Queue";
import { RunsPage } from "./pages/Runs";

function UserBar() {
  const { who, signOut } = useSession();
  if (!who) return null;
  return (
    <div className="session">
      <span>{who.user.name} · {who.user.role} · {who.tenant.slug}</span>
      <button onClick={() => void signOut()}>Sign out</button>
    </div>
  );
}

export default function App() {
  const { status, who } = useSession();
  if (status === "loading") return <main><p className="muted">Loading…</p></main>;
  if (status === "anonymous") return <main><LoginPage /></main>;
  return (
    <>
      <header className="top">
        <strong>Pulse</strong>
        <nav>
          {navFor(who?.user.role ?? "csm").map((n) => <NavLink key={n.to} to={n.to} end={n.to === "/"}>{n.label}</NavLink>)}
        </nav>
        <UserBar />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route path="/low-confidence" element={<LowConfidencePage />} />
          <Route path="/accounts/:id" element={<AccountPage />} />
          <Route path="/drafts" element={<DraftsPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/admin" element={<AdminPage />} />
        </Routes>
      </main>
    </>
  );
}
