import { Suspense, useEffect } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { RouteAnnouncer, SkipLink } from "./components/A11y";  // А11: пропуск навигации, смена экрана
import { JuryGuide } from "./components/JuryGuide";
import { StudyDock } from "./components/study/StudyDock";
import { RouteBoundary, RouteFallback } from "./components/Boot";  // Я16: загрузка экрана, ошибка загрузки — экран повтора
import Landing from "./pages/Landing";
import { candidateSections } from "./pages/candidate/sections";
import { employerSections } from "./pages/employer/sections";
import { panelSections } from "./pages/expert/sections";
import { fspSections } from "./ideas/fsp/sections";
import { HashScroll } from "./lib/hashScroll";
import { lazyNamed } from "./lib/lazyPage";
import { preloadSections } from "./lib/preload";

// Я16: стартовый JS — общий код и главная (первый экран жюри). Остальные экраны — ленивыми файлами сборки по
// модулям: роли (кандидат, работодатель, эксперт, ФСП) и тяжёлые экраны (валидация, критерии, графики) грузятся
// при первом переходе. Один модуль = один файл, сколько бы экранов из него ни брали.
const pg = {
  cabinet: () => import("./components/CabinetLayout"),
  studyAbout: () => import("./pages/StudyAbout"),
  expert: () => import("./pages/Expert"),
  panel: () => import("./pages/expert/Panel"),
  validation: () => import("./pages/Validation"),
  login: () => import("./pages/Login"),
  register: () => import("./pages/Register"),
  security: () => import("./pages/Security"),
  verify: () => import("./pages/Verify"),
  assessment: () => import("./pages/candidate/Assessment"),
  category: () => import("./pages/candidate/Category"),
  attempts: () => import("./pages/candidate/Attempts"),  // И26: две попытки теста рядом
  feedback: () => import("./pages/candidate/Feedback"),
  contact: () => import("./pages/candidate/Contact"),
  messages: () => import("./pages/Messages"),
  candOverview: () => import("./pages/candidate/Overview"),
  myData: () => import("./pages/candidate/MyData"),
  profile: () => import("./pages/candidate/Profile"),
  settings: () => import("./pages/candidate/Settings"),
  empContact: () => import("./pages/employer/Contact"),
  compare: () => import("./pages/employer/Compare"),
  needs: () => import("./pages/employer/Needs"),
  mutual: () => import("./pages/mutual/Employer"),  // взаимный подбор, ссылка руководителю (Н9, Н2, Н3)
  share: () => import("./pages/mutual/Share"),
  empOverview: () => import("./pages/employer/Overview"),
  search: () => import("./pages/employer/Search"),
  appInstall: () => import("./integrations/AppInstall"),
  notifications: () => import("./pages/Notifications"),
  ats: () => import("./integrations/Ats"),
  companyPublic: () => import("./integrations/CompanyPublic"),
  fspId: () => import("./integrations/FspId"),
  sus: () => import("./integrations/Sus"),
  vacancies: () => import("./integrations/Vacancies"),
  assignCand: () => import("./pages/assignments/Candidate"),  // задания работодателя (И7)
  assignEmp: () => import("./pages/assignments/Employer"),
  cupCand: () => import("./ideas/cup/Candidate"),
  cupEmp: () => import("./ideas/cup/Employer"),
  fsp: () => import("./ideas/fsp/Cabinet"),
  liveGuest: () => import("./ideas/live/Guest"),
  liveScreen: () => import("./ideas/live/Screen"),
  passport: () => import("./passport/VerifyPage"),
  criteria: () => import("./pages/Criteria"),  // К1: проверка по критериям ТЗ
  interview: () => import("./components/Interview"),  // Я15: разговор устной защиты и ИИ-интервью
  tariffs: () => import("./pages/employer/Tariffs"),  // Я29: тарифы работодателя (TARIFFS_ENABLED)
  fspBenefit: () => import("./ideas/fsp/Benefit"),  // Я29: «Польза для ФСП» и «Партнёры ФСП»
};

// FIX7: файлы основных разделов маршрута жюри — заранее, когда браузер свободен (lib/preload.ts): переход в раздел
// не ждёт сеть. Порядок — как в проводнике жюри: кабинет, тест, потребности и подборка, карточка, валидация, критерии.
const PRELOAD = [pg.cabinet, pg.assessment, pg.needs, pg.search, pg.validation, pg.criteria, pg.category, pg.compare, pg.feedback];

const CabinetLayout = lazyNamed(pg.cabinet, "CabinetLayout");
const InterviewRoom = lazyNamed(pg.interview, "InterviewRoom");
const TariffsPublic = lazyNamed(pg.tariffs, "default");
const EmployerTariffs = lazyNamed(pg.tariffs, "EmployerTariffs");
const FspBenefit = lazyNamed(pg.fspBenefit, "FspBenefit");
const FspPartners = lazyNamed(pg.fspBenefit, "FspPartners");
const StudyAbout = lazyNamed(pg.studyAbout, "default");
const Expert = lazyNamed(pg.expert, "default");
const ExpertAngoff = lazyNamed(pg.panel, "ExpertAngoff");
const ExpertAnswers = lazyNamed(pg.panel, "ExpertAnswers");
const ExpertHome = lazyNamed(pg.panel, "ExpertHome");
const ExpertInvite = lazyNamed(pg.panel, "ExpertInvite");
const ExpertPairs = lazyNamed(pg.panel, "ExpertPairs");
const Validation = lazyNamed(pg.validation, "default");
const Login = lazyNamed(pg.login, "default");
const Register = lazyNamed(pg.register, "default");
const TwoFactorLogin = lazyNamed(pg.security, "TwoFactorLogin");
const TwoFactorSettings = lazyNamed(pg.security, "TwoFactorSettings");
const Verify = lazyNamed(pg.verify, "default");
const Assessment = lazyNamed(pg.assessment, "default");
const TestRun = lazyNamed(pg.assessment, "TestRun");
const Category = lazyNamed(pg.category, "default");
const Attempts = lazyNamed(pg.attempts, "default");
const Feedback = lazyNamed(pg.feedback, "default");
const Invitations = lazyNamed(pg.contact, "Invitations");
const Probes = lazyNamed(pg.contact, "Probes");
const Messages = lazyNamed(pg.messages, "Messages");
const CandidateOverview = lazyNamed(pg.candOverview, "default");
const MyData = lazyNamed(pg.myData, "default");
const Profile = lazyNamed(pg.profile, "default");
const Fsp = lazyNamed(pg.settings, "Fsp");
const Settings = lazyNamed(pg.settings, "Settings");
const EmployerInvitations = lazyNamed(pg.empContact, "EmployerInvitations");
const EmployerProbes = lazyNamed(pg.empContact, "EmployerProbes");
const Compare = lazyNamed(pg.compare, "Compare");
const CompareLanding = lazyNamed(pg.compare, "CompareLanding");
const Needs = lazyNamed(pg.needs, "Needs");
const Selection = lazyNamed(pg.needs, "Selection");
const MutualEntry = lazyNamed(pg.mutual, "MutualEntry");
const SharePage = lazyNamed(pg.share, "SharePage");
const EmployerOverview = lazyNamed(pg.empOverview, "default");
const Company = lazyNamed(pg.empOverview, "Company");
const CandidateDetail = lazyNamed(pg.search, "CandidateDetail");
const Search = lazyNamed(pg.search, "Search");
const AppSection = lazyNamed(pg.appInstall, "AppSection");
const InstallPage = lazyNamed(pg.appInstall, "InstallPage");
const Notifications = lazyNamed(pg.notifications, "default");
const EmployerAts = lazyNamed(pg.ats, "EmployerAts");
const CompanyPublic = lazyNamed(pg.companyPublic, "CompanyPublic");
const FspIdDone = lazyNamed(pg.fspId, "FspIdDone");
const AdminSus = lazyNamed(pg.sus, "AdminSus");
const SusPage = lazyNamed(pg.sus, "SusPage");
const CandidateVacancies = lazyNamed(pg.vacancies, "CandidateVacancies");
const EmployerVacancies = lazyNamed(pg.vacancies, "EmployerVacancies");
const CandidateAssignment = lazyNamed(pg.assignCand, "CandidateAssignment");
const CandidateAssignments = lazyNamed(pg.assignCand, "CandidateAssignments");
const EmployerAssignment = lazyNamed(pg.assignEmp, "EmployerAssignment");
const EmployerAssignments = lazyNamed(pg.assignEmp, "EmployerAssignments");
const CandidateCup = lazyNamed(pg.cupCand, "CandidateCup");
const CandidateCups = lazyNamed(pg.cupCand, "CandidateCups");
const EmployerCup = lazyNamed(pg.cupEmp, "EmployerCup");
const EmployerCups = lazyNamed(pg.cupEmp, "EmployerCups");
const FspCups = lazyNamed(pg.fsp, "FspCups");
const FspDemand = lazyNamed(pg.fsp, "FspDemand");
const FspEffect = lazyNamed(pg.fsp, "FspEffect");
const FspFunnel = lazyNamed(pg.fsp, "FspFunnel");
const FspMethod = lazyNamed(pg.fsp, "FspMethod");
const FspOverview = lazyNamed(pg.fsp, "FspOverview");
const FspReportLayout = lazyNamed(pg.fsp, "FspReportLayout");
const FspSalaries = lazyNamed(pg.fsp, "FspSalaries");
const LiveGuest = lazyNamed(pg.liveGuest, "default");
const LiveScreen = lazyNamed(pg.liveScreen, "default");
const PassportVerify = lazyNamed(pg.passport, "default");
const Criteria = lazyNamed(pg.criteria, "default");
const JuryGo = lazyNamed(pg.criteria, "JuryGo");

export default function App() {
  useEffect(() => { preloadSections(PRELOAD); }, []);
  return (
    <>
    <SkipLink />
    <RouteBoundary>
    <Suspense fallback={<RouteFallback />}>
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/validation" element={<Validation />} />
      <Route path="/criteria" element={<Criteria />} />
      <Route path="/jury/go" element={<JuryGo />} />
      <Route path="/study" element={<StudyAbout />} />
      <Route path="/tariffs" element={<TariffsPublic />} />
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
      <Route path="/share/:token" element={<SharePage />} />
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
        <Route path="interview/:id" element={<InterviewRoom />} />
        <Route path="feedback" element={<Feedback />} />
        <Route path="profile" element={<Profile />} />
        <Route path="invitations" element={<Invitations />} />
        <Route path="messages" element={<Messages role="candidate" />} />
        <Route path="probes" element={<Probes />} />
        <Route path="fsp" element={<Fsp />} />
        <Route path="settings" element={<Settings />} />
        <Route path="mydata" element={<MyData />} />
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
        <Route path="mutual" element={<MutualEntry />} />
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
        <Route path="tariffs" element={<EmployerTariffs />} />
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
        <Route path="benefit" element={<FspBenefit />} />
        <Route path="partners" element={<FspPartners />} />
        <Route path="security" element={<TwoFactorSettings />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
    </Suspense>
    </RouteBoundary>
    <JuryGuide />
    <HashScroll />
    <StudyDock />
    <RouteAnnouncer />
    </>
  );
}

function NotFound() {
  return (
    <main id="main" className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="text-6xl font-extrabold text-brand" aria-hidden="true">404</p>
      <h1 className="text-xl font-bold text-brand-night">Такой страницы нет</h1>
      <p className="max-w-sm text-sm text-brand-ink/70">Возможно, ссылка устарела. Демо-учётки для жюри — на главной, вход в один клик.</p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link to="/" className="btn-primary">На главную</Link>
        <Link to="/#jury" className="btn-ghost">Демо для жюри</Link>
      </div>
    </main>
  );
}
