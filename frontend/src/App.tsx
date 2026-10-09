import { Link, Route, Routes } from "react-router-dom";
import { CabinetLayout } from "./components/CabinetLayout";
import { JuryGuide } from "./components/JuryGuide";
import Expert from "./pages/Expert";
import { ExpertAngoff, ExpertAnswers, ExpertHome, ExpertInvite, ExpertPairs, panelSections } from "./pages/expert/Panel";
import Validation from "./pages/Validation";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import { TwoFactorLogin, TwoFactorSettings } from "./pages/Security";
import Verify from "./pages/Verify";
import Assessment, { TestRun } from "./pages/candidate/Assessment";
import Category from "./pages/candidate/Category";
import Attempts from "./pages/candidate/Attempts";  // И26: две попытки теста рядом
import Feedback from "./pages/candidate/Feedback";
import { Invitations, Probes } from "./pages/candidate/Contact";
import { Messages } from "./pages/Messages";
import CandidateOverview from "./pages/candidate/Overview";
import Profile from "./pages/candidate/Profile";
import { Fsp, Settings } from "./pages/candidate/Settings";
import { candidateSections } from "./pages/candidate/sections";
import { EmployerInvitations, EmployerProbes } from "./pages/employer/Contact";
import { Compare, CompareLanding } from "./pages/employer/Compare";
import { Needs, Selection } from "./pages/employer/Needs";
import EmployerOverview, { Company } from "./pages/employer/Overview";
import { CandidateDetail, Search } from "./pages/employer/Search";
import { employerSections } from "./pages/employer/sections";
import { AppSection, InstallPage } from "./integrations/AppInstall";
import Notifications from "./pages/Notifications";
import { EmployerAts } from "./integrations/Ats";
import { CompanyPublic } from "./integrations/CompanyPublic";
import { FspIdDone } from "./integrations/FspId";
import { AdminSus, SusPage } from "./integrations/Sus";
import { CandidateVacancies, EmployerVacancies } from "./integrations/Vacancies";
import { CandidateAssignment, CandidateAssignments } from "./pages/assignments/Candidate";  // задания работодателя (И7)
import { EmployerAssignment, EmployerAssignments } from "./pages/assignments/Employer";
import { CandidateCup, CandidateCups } from "./ideas/cup/Candidate";
import { EmployerCup, EmployerCups } from "./ideas/cup/Employer";
import { FspCups, FspDemand, FspEffect, FspFunnel, FspMethod, FspOverview, FspReportLayout, FspSalaries } from "./ideas/fsp/Cabinet";
import { fspSections } from "./ideas/fsp/sections";
import LiveGuest from "./ideas/live/Guest";
import LiveScreen from "./ideas/live/Screen";
import PassportVerify from "./passport/VerifyPage";

export default function App() {
  return (
    <>
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/validation" element={<Validation />} />
      <Route path="/jury/live" element={<LiveScreen />} />
      <Route path="/j/:code" element={<LiveGuest />} />
      <Route path="/expert" element={<CabinetLayout role="expert" alsoRoles={["admin"]} title="Кабинет эксперта" sections={panelSections} />}>
        <Route index element={<ExpertHome />} />
        <Route path="pairs" element={<ExpertPairs />} />
        <Route path="answers" element={<ExpertAnswers />} />
        <Route path="angoff" element={<ExpertAngoff />} />
        <Route path="review" element={<Expert />} />
        <Route path="security" element={<TwoFactorSettings />} />
      </Route>
      <Route path="/expert-invite/:token" element={<ExpertInvite />} />
      <Route path="/register" element={<Register />} />
      <Route path="/verify" element={<Verify />} />
      <Route path="/verify/:id" element={<PassportVerify />} />
      <Route path="/login" element={<Login />} />
      <Route path="/login/2fa" element={<TwoFactorLogin />} />
      <Route path="/fsp-id/done" element={<FspIdDone />} />
      <Route path="/install" element={<InstallPage />} />
      <Route path="/sus" element={<SusPage />} />
      <Route path="/admin/sus" element={<AdminSus />} />
      <Route path="/candidate" element={<CabinetLayout role="candidate" title="Кабинет кандидата" sections={candidateSections} />}>
        <Route index element={<CandidateOverview />} />
        <Route path="assessment" element={<Assessment />} />
        {/* «Пройдите тест сами» (жюри): тот же экран выбора грейда с экспресс-режимом, выбранным заранее */}
        <Route path="express" element={<Assessment express />} />
        <Route path="assessment/test/:id" element={<TestRun />} />
        <Route path="category" element={<Category />} />
        <Route path="attempts" element={<Attempts />} />
        <Route path="feedback" element={<Feedback />} />
        <Route path="profile" element={<Profile />} />
        <Route path="invitations" element={<Invitations />} />
        <Route path="messages" element={<Messages role="candidate" />} />
        <Route path="probes" element={<Probes />} />
        <Route path="fsp" element={<Fsp />} />
        <Route path="settings" element={<Settings />} />
        <Route path="vacancies" element={<CandidateVacancies />} />
        <Route path="companies/:id" element={<CompanyPublic />} />
        <Route path="app" element={<AppSection />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="cups" element={<CandidateCups />} />
        <Route path="cups/:id" element={<CandidateCup />} />
        <Route path="assignments" element={<CandidateAssignments />} />
        <Route path="assignments/:id" element={<CandidateAssignment />} />
      </Route>
      <Route path="/employer" element={<CabinetLayout role="employer" title="Кабинет работодателя" sections={employerSections} />}>
        <Route index element={<EmployerOverview />} />
        <Route path="company" element={<Company />} />
        <Route path="needs" element={<Needs />} />
        <Route path="needs/:id" element={<Selection />} />
        <Route path="needs/:id/v/:version" element={<Selection />} />
        <Route path="needs/:id/compare" element={<Compare />} />
        <Route path="compare" element={<CompareLanding />} />
        <Route path="search" element={<Search />} />
        <Route path="candidates/:ref" element={<CandidateDetail />} />
        <Route path="probes" element={<EmployerProbes />} />
        <Route path="invitations" element={<EmployerInvitations />} />
        <Route path="messages" element={<Messages role="employer" />} />
        <Route path="vacancies" element={<EmployerVacancies />} />
        <Route path="ats" element={<EmployerAts />} />
        <Route path="app" element={<AppSection />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="cups" element={<EmployerCups />} />
        <Route path="cups/:id" element={<EmployerCup />} />
        <Route path="assignments" element={<EmployerAssignments />} />
        <Route path="assignments/:id" element={<EmployerAssignment />} />
      </Route>
      <Route path="/fsp" element={<CabinetLayout role="fsp_analyst" alsoRoles={["admin"]} title="Кабинет ФСП" sections={fspSections} />}>
        <Route element={<FspReportLayout />}>
          <Route index element={<FspOverview />} />
          <Route path="demand" element={<FspDemand />} />
          <Route path="effect" element={<FspEffect />} />
          <Route path="salaries" element={<FspSalaries />} />
          <Route path="funnel" element={<FspFunnel />} />
          <Route path="cups" element={<FspCups />} />
          <Route path="method" element={<FspMethod />} />
        </Route>
        <Route path="security" element={<TwoFactorSettings />} />
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
      <p className="text-6xl font-extrabold text-brand" aria-hidden="true">404</p>
      <h1 className="text-xl font-bold text-brand-night">Такой страницы нет</h1>
      <p className="max-w-sm text-sm text-brand-ink/70">Возможно, ссылка устарела. Демо-учётки для жюри — на главной, вход в один клик.</p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link to="/" className="btn-primary">На главную</Link>
        <Link to="/#jury" className="btn-ghost">Демо для жюри</Link>
      </div>
    </div>
  );
}
