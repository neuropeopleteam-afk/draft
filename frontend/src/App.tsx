import { Link, Route, Routes } from "react-router-dom";
import { CabinetLayout } from "./components/CabinetLayout";
import { JuryGuide } from "./components/JuryGuide";
import Expert from "./pages/Expert";
import Validation from "./pages/Validation";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Verify from "./pages/Verify";
import Assessment, { TestRun } from "./pages/candidate/Assessment";
import Category from "./pages/candidate/Category";
import { Invitations, Probes } from "./pages/candidate/Contact";
import CandidateOverview from "./pages/candidate/Overview";
import Profile from "./pages/candidate/Profile";
import { Fsp, Settings } from "./pages/candidate/Settings";
import { candidateSections } from "./pages/candidate/sections";
import { EmployerInvitations, EmployerProbes } from "./pages/employer/Contact";
import { Needs, Selection } from "./pages/employer/Needs";
import EmployerOverview, { Company } from "./pages/employer/Overview";
import { CandidateDetail, Search } from "./pages/employer/Search";
import { employerSections } from "./pages/employer/sections";
import { AppSection, InstallPage } from "./integrations/AppInstall";
import { EmployerAts } from "./integrations/Ats";
import { CompanyPublic } from "./integrations/CompanyPublic";
import { FspIdDone } from "./integrations/FspId";
import { AdminSus, SusPage } from "./integrations/Sus";
import { CandidateVacancies, EmployerVacancies } from "./integrations/Vacancies";

export default function App() {
  return (
    <>
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/validation" element={<Validation />} />
      <Route path="/expert" element={<CabinetLayout role="admin" title="Кабинет эксперта" sections={[]} />}>
        <Route index element={<Expert />} />
      </Route>
      <Route path="/register" element={<Register />} />
      <Route path="/verify" element={<Verify />} />
      <Route path="/login" element={<Login />} />
      <Route path="/fsp-id/done" element={<FspIdDone />} />
      <Route path="/install" element={<InstallPage />} />
      <Route path="/sus" element={<SusPage />} />
      <Route path="/admin/sus" element={<AdminSus />} />
      <Route path="/candidate" element={<CabinetLayout role="candidate" title="Кабинет кандидата" sections={candidateSections} />}>
        <Route index element={<CandidateOverview />} />
        <Route path="assessment" element={<Assessment />} />
        <Route path="assessment/test/:id" element={<TestRun />} />
        <Route path="category" element={<Category />} />
        <Route path="profile" element={<Profile />} />
        <Route path="invitations" element={<Invitations />} />
        <Route path="probes" element={<Probes />} />
        <Route path="fsp" element={<Fsp />} />
        <Route path="settings" element={<Settings />} />
        <Route path="vacancies" element={<CandidateVacancies />} />
        <Route path="companies/:id" element={<CompanyPublic />} />
        <Route path="app" element={<AppSection />} />
      </Route>
      <Route path="/employer" element={<CabinetLayout role="employer" title="Кабинет работодателя" sections={employerSections} />}>
        <Route index element={<EmployerOverview />} />
        <Route path="company" element={<Company />} />
        <Route path="needs" element={<Needs />} />
        <Route path="needs/:id" element={<Selection />} />
        <Route path="needs/:id/v/:version" element={<Selection />} />
        <Route path="search" element={<Search />} />
        <Route path="candidates/:ref" element={<CandidateDetail />} />
        <Route path="probes" element={<EmployerProbes />} />
        <Route path="invitations" element={<EmployerInvitations />} />
        <Route path="vacancies" element={<EmployerVacancies />} />
        <Route path="ats" element={<EmployerAts />} />
        <Route path="app" element={<AppSection />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
    <JuryGuide />
    </>
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
