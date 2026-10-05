import { Link, Route, Routes } from "react-router-dom";
import { CabinetLayout, SectionPlaceholder } from "./components/CabinetLayout";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Verify from "./pages/Verify";
import CandidateOverview from "./pages/candidate/Overview";
import { candidateSections } from "./pages/candidate/sections";
import EmployerOverview from "./pages/employer/Overview";
import { employerSections } from "./pages/employer/sections";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/register" element={<Register />} />
      <Route path="/verify" element={<Verify />} />
      <Route path="/login" element={<Login />} />
      <Route path="/candidate" element={<CabinetLayout role="candidate" title="Кабинет кандидата" sections={candidateSections} />}>
        <Route index element={<CandidateOverview />} />
        {candidateSections.map((s) => <Route key={s.path} path={s.path} element={<SectionPlaceholder section={s} />} />)}
      </Route>
      <Route path="/employer" element={<CabinetLayout role="employer" title="Кабинет работодателя" sections={employerSections} />}>
        <Route index element={<EmployerOverview />} />
        {employerSections.map((s) => <Route key={s.path} path={s.path} element={<SectionPlaceholder section={s} />} />)}
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="text-6xl font-extrabold text-brand">404</p>
      <p className="text-brand-ink/70">Такой страницы нет.</p>
      <Link to="/" className="btn-primary">На главную</Link>
    </div>
  );
}
