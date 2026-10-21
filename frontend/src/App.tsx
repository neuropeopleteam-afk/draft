import { Suspense, useEffect, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { RouteAnnouncer, SkipLink } from "./components/A11y";
import { RouteBoundary, RouteFallback, hardReload } from "./components/Boot";
import Landing from "./pages/Landing";
import { candidateSections } from "./pages/candidate/sections";
import { employerSections } from "./pages/employer/sections";
import { panelSections } from "./pages/expert/sections";
import { fspSections } from "./ideas/fsp/sections";
import { useAuth } from "./lib/auth";
import { HashScroll } from "./lib/hashScroll";
import { juryLogin } from "./lib/jury";
import { useDemoAccess, useDemoUi } from "./lib/juryMode";
import { lazyNamed } from "./lib/lazyPage";
import { preloadSections } from "./lib/preload";

const pg = {
  cabinet: () => import("./components/CabinetLayout"),
  studyAbout: () => import("./pages/StudyAbout"),
  expert: () => import("./pages/Expert"),
  panel: () => import("./pages/expert/Panel"),
  validation: () => import("./pages/Validation"),
  login: () => import("./pages/Login"),
  register: () => import("./pages/Register"),
  forgot: () => import("./pages/ForgotPassword"),
  security: () => import("./pages/Security"),
  verify: () => import("./pages/Verify"),
  assessment: () => import("./pages/candidate/Assessment"),
  category: () => import("./pages/candidate/Category"),
  attempts: () => import("./pages/candidate/Attempts"),
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
  mutual: () => import("./pages/mutual/Employer"),
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
  assignCand: () => import("./pages/assignments/Candidate"),
  assignEmp: () => import("./pages/assignments/Employer"),
  cupCand: () => import("./ideas/cup/Candidate"),
  cupEmp: () => import("./ideas/cup/Employer"),
  fsp: () => import("./ideas/fsp/Cabinet"),
  liveGuest: () => import("./ideas/live/Guest"),
  livePitch: () => import("./pages/demo/LivePitch"),
  passport: () => import("./passport/VerifyPage"),
  criteria: () => import("./pages/Criteria"),
  interview: () => import("./components/Interview"),
  tariffs: () => import("./pages/employer/Tariffs"),
  monetization: () => import("./pages/public/Monetization"),
  legal: () => import("./pages/public/Legal"),
  trio: () => import("./pages/trio/Trio"),
  fspBenefit: () => import("./ideas/fsp/Benefit"),
  demoHub: () => import("./pages/demo/DemoHub"),
  warroom: () => import("./pages/WarRoom"),
  squad: () => import("./pages/employer/SquadDraft"),
  support: () => import("./pages/support/Support"),
  admin: () => import("./pages/admin/Admin"),
};

const PRELOAD = [pg.cabinet, pg.assessment, pg.needs, pg.search, pg.validation, pg.criteria, pg.category, pg.compare, pg.feedback];

const CabinetLayout = lazyNamed(pg.cabinet, "CabinetLayout");
const InterviewRoom = lazyNamed(pg.interview, "InterviewRoom");
const Monetization = lazyNamed(pg.monetization, "default");
const LegalPage = lazyNamed(pg.legal, "default");
const TrioPage = lazyNamed(pg.trio, "TrioPage");
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
const ForgotPassword = lazyNamed(pg.forgot, "ForgotPassword");
const ResetPassword = lazyNamed(pg.forgot, "ResetPassword");
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
const SquadDraft = lazyNamed(pg.squad, "default");
const FspCups = lazyNamed(pg.fsp, "FspCups");
const FspDemand = lazyNamed(pg.fsp, "FspDemand");
const FspEffect = lazyNamed(pg.fsp, "FspEffect");
const FspFunnel = lazyNamed(pg.fsp, "FspFunnel");
const FspMethod = lazyNamed(pg.fsp, "FspMethod");
const FspOverview = lazyNamed(pg.fsp, "FspOverview");
const FspReportLayout = lazyNamed(pg.fsp, "FspReportLayout");
const FspSalaries = lazyNamed(pg.fsp, "FspSalaries");
const LiveGuest = lazyNamed(pg.liveGuest, "default");
const LivePitch = lazyNamed(pg.livePitch, "default");
const PassportVerify = lazyNamed(pg.passport, "default");
const Criteria = lazyNamed(pg.criteria, "default");
const JuryGo = lazyNamed(pg.criteria, "JuryGo");
const DemoHub = lazyNamed(pg.demoHub, "default");
const WarRoom = lazyNamed(pg.warroom, "default");
const Support = lazyNamed(pg.support, "default");
const Admin = lazyNamed(pg.admin, "default");
const JuryGuide = lazyNamed(() => import("./components/JuryGuide"), "JuryGuide");
const InteractiveAvatarTour = lazyNamed(() => import("./components/InteractiveAvatarTour"), "InteractiveAvatarTour");
const StudyDock = lazyNamed(() => import("./components/study/StudyDock"), "StudyDock");

/** Переадресация со старого демо-маршрута с сохранением query и hash (для обзора Насти и закладок). */
function RedirectPreserve({ to }: { to: string }) {
  const loc = useLocation();
  return <Navigate to={`${to}${loc.search}${loc.hash}`} replace />;
}

/** Ограничение доступа к /demo/* при выключенном демо-режиме на сервере. */
function DemoGuard({ children }: { children: React.ReactElement }) {
  const ok = useDemoAccess();
  if (!ok) return <NotFound />;
  return children;
}

/** Автоматический вход демо-аналитиком ФСП при переходе на /demo/fsp-benefit → /fsp/benefit внутри CabinetLayout. */
function DemoFspBenefitRedirect() {
  const { me, signIn, loading } = useAuth();
  const navigate = useNavigate();
  const started = useRef(false);
  useEffect(() => {
    if (loading || started.current) return;
    if (me?.role === "fsp_analyst" || me?.role === "admin") {
      navigate("/fsp/benefit", { replace: true });
      return;
    }
    started.current = true;
    juryLogin("fsp", signIn, "/fsp/benefit")
      .then((to) => navigate(to, { replace: true }))
      .catch(() => navigate("/login", { replace: true }));
  }, [loading, me?.role, signIn, navigate]);
  return <RouteFallback />;
}

export default function App() {
  useEffect(() => { preloadSections(PRELOAD); }, []);
  return (
    <>
    <SkipLink />
    <RouteBoundary>
    <Suspense fallback={<RouteFallback />}>
    <Routes>
      <Route path="/" element={<Landing />} />

      {/* Раздел «Демо для жюри» (/demo/*) и совместимые прямые маршруты для e2e/проводника */}
      <Route path="/demo" element={<DemoGuard><DemoHub /></DemoGuard>} />
      <Route path="/demo/register" element={<DemoGuard><Register demoPreview /></DemoGuard>} />
      <Route path="/demo/warroom" element={<DemoGuard><WarRoom /></DemoGuard>} />
      <Route path="/demo/validation" element={<DemoGuard><Validation /></DemoGuard>} />
      <Route path="/demo/criteria" element={<DemoGuard><Criteria /></DemoGuard>} />
      <Route path="/demo/live" element={<DemoGuard><LivePitch /></DemoGuard>} />
      <Route path="/demo/go" element={<DemoGuard><JuryGo /></DemoGuard>} />
      <Route path="/demo/fsp-benefit" element={<DemoGuard><DemoFspBenefitRedirect /></DemoGuard>} />

      <Route path="/expertise" element={<RedirectPreserve to="/demo" />} />
      <Route path="/warroom" element={<DemoGuard><WarRoom /></DemoGuard>} />
      <Route path="/validation" element={<DemoGuard><Validation /></DemoGuard>} />
      <Route path="/criteria" element={<DemoGuard><Criteria /></DemoGuard>} />
      <Route path="/jury/live" element={<RedirectPreserve to="/demo/live" />} />
      <Route path="/jury/go" element={<DemoGuard><JuryGo /></DemoGuard>} />
      <Route path="/security" element={<Navigate to="/validation#red-button" replace />} />
      <Route path="/tariffs/live" element={<Navigate to="/pricing" replace />} />

      <Route path="/study" element={<StudyAbout />} />
      <Route path="/tariffs" element={<Monetization />} />
      <Route path="/pricing" element={<Monetization />} />
      <Route path="/support" element={<Support />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="/admin/sus" element={<AdminSus />} />
      {["/privacy", "/consent", "/terms", "/cookies", "/recommendations"].map((p) => <Route key={p} path={p} element={<LegalPage />} />)}
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
      <Route path="/forgot" element={<ForgotPassword />} />
      <Route path="/reset" element={<ResetPassword />} />
      <Route path="/login/2fa" element={<TwoFactorLogin />} />
      <Route path="/fsp-id/done" element={<FspIdDone />} />
      <Route path="/install" element={<InstallPage />} />
      <Route path="/sus" element={<SusPage />} />
      <Route path="/candidate" element={<CabinetLayout role="candidate" title="Кабинет кандидата" sections={candidateSections} />}>
        <Route index element={<CandidateOverview />} />
        <Route path="assessment" element={<Assessment />} />
        <Route path="express" element={<Assessment express />} />
        <Route path="assessment/test/:id" element={<TestRun />} />
        <Route path="category" element={<Category />} />
        <Route path="attempts" element={<Attempts />} />
        <Route path="interview/:id" element={<InterviewRoom />} />
        <Route path="feedback" element={<Feedback />} />
        <Route path="profile" element={<Profile />} />
        <Route path="invitations" element={<Invitations />} />
        <Route path="messages" element={<Messages role="candidate" />} />
        <Route path="trio" element={<TrioPage role="candidate" />} />
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
        <Route path="contact" element={<Navigate to="/candidate/invitations" replace />} />
        <Route path="mutual" element={<Navigate to="/candidate/settings" replace />} />
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
        <Route path="squad" element={<SquadDraft />} />
        <Route path="search" element={<Search />} />
        <Route path="candidates/:ref" element={<CandidateDetail />} />
        <Route path="probes" element={<EmployerProbes />} />
        <Route path="invitations" element={<EmployerInvitations />} />
        <Route path="messages" element={<Messages role="employer" />} />
        <Route path="trio" element={<TrioPage role="employer" />} />
        <Route path="vacancies" element={<EmployerVacancies />} />
        <Route path="ats" element={<EmployerAts />} />
        <Route path="app" element={<AppSection />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="cups" element={<EmployerCups />} />
        <Route path="cups/:id" element={<EmployerCup />} />
        <Route path="assignments" element={<EmployerAssignments />} />
        <Route path="assignments/:id" element={<EmployerAssignment />} />
        <Route path="tariffs" element={<EmployerTariffs />} />
        <Route path="subscriptions" element={<Navigate to="/employer/notifications" replace />} />
        <Route path="applications" element={<Navigate to="/employer/vacancies" replace />} />
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
        <Route path="trio" element={<TrioPage role="fsp" />} />
        <Route path="security" element={<TwoFactorSettings />} />
        <Route path="analytics" element={<Navigate to="/fsp/demand" replace />} />
        <Route path="regions" element={<Navigate to="/fsp/demand" replace />} />
        <Route path="map" element={<Navigate to="/fsp/demand" replace />} />
      </Route>
      <Route path="/500" element={<ServerErrorPage />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
    </Suspense>
    </RouteBoundary>
    <Suspense fallback={null}>
      <JuryGuide />
      <InteractiveAvatarTour />
      <StudyDock />
    </Suspense>
    <HashScroll />
    <CookieBanner />
    <RouteAnnouncer />
    </>
  );
}

const COOKIE_KEY = "draft_cookie_consent";

function CookieBanner() {
  const [choice, setChoice] = useState<string | null>(() => {
    try {
      return localStorage.getItem(COOKIE_KEY);
    } catch {
      return "essential";
    }
  });
  const loc = useLocation();
  if (
    choice ||
    loc.pathname.startsWith("/j/") ||
    ["/login", "/register", "/demo/register", "/verify", "/forgot", "/reset", "/500"].includes(loc.pathname)
  ) {
    return null;
  }

  function pick(val: "essential" | "all") {
    try {
      localStorage.setItem(COOKIE_KEY, val);
    } catch { /* ignore */ }
    setChoice(val);
  }

  return (
    <aside
      aria-label="Настройки файлов cookie"
      data-testid="cookie-banner"
      className="fixed inset-x-3 bottom-[calc(5.25rem+var(--mobile-tabbar-h,0px))] z-40 rounded-2xl border border-brand-night/15 bg-white/95 p-3.5 text-xs text-brand-ink shadow-xl backdrop-blur sm:bottom-[calc(0.75rem+var(--mobile-tabbar-h,0px))] sm:left-4 sm:right-56 sm:max-w-xl sm:flex sm:items-center sm:justify-between sm:gap-4 sm:p-4 print:hidden"
    >
      <p className="leading-relaxed">
        Мы используем файлы cookie для авторизации, безопасности входа и работы личного кабинета (без сторонних рекламных счётчиков). Подробнее — в{" "}
        <Link to="/cookies" className="font-semibold text-brand hover:underline">Политике использования cookie</Link>.
      </p>
      <div className="mt-3 flex shrink-0 flex-wrap gap-2 sm:mt-0">
        <button
          type="button"
          onClick={() => pick("essential")}
          data-testid="cookie-essential"
          className="rounded-xl border border-brand-night/15 bg-white px-3 py-1.5 font-semibold text-brand-night hover:bg-brand-blush/40"
        >
          Только необходимые
        </button>
        <button
          type="button"
          onClick={() => pick("all")}
          data-testid="cookie-accept-all"
          className="rounded-xl bg-brand px-3.5 py-1.5 font-bold text-white hover:bg-brand-deep"
        >
          Принять все
        </button>
      </div>
    </aside>
  );
}

function NotFound() {
  const demoUi = useDemoUi();
  return (
    <main id="main" tabIndex={-1} className="flex min-h-screen flex-col items-center justify-center bg-[#FAF8FC] px-4 py-10 text-center outline-none" data-testid="not-found-page">
      <div className="mx-auto flex w-full max-w-lg flex-col items-center gap-4 rounded-3xl border border-brand-night/10 bg-white p-7 shadow-sm sm:p-9">
        <div className="inline-flex items-center gap-2.5 text-sm font-extrabold text-brand-night">
          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="#0E1126" />
            <circle cx="12.5" cy="16" r="7" fill="none" stroke="#DCE2FF" strokeWidth="2.5" />
            <circle cx="19.5" cy="16" r="7" fill="none" stroke="#EC1D35" strokeWidth="2.5" />
          </svg>
          <span>Драфт</span>
          <span className="rounded-full bg-brand-blush/80 px-2.5 py-0.5 font-mono text-xs font-extrabold text-brand-night">404</span>
        </div>
        <p className="text-5xl font-extrabold text-brand sm:text-6xl" aria-hidden="true">404</p>
        <h1 className="text-xl font-extrabold text-brand-night sm:text-2xl">Такой страницы нет</h1>
        <p className="max-w-md text-sm leading-relaxed text-brand-ink/75">
          Возможно, ссылка устарела или страница была перемещена. Вернитесь на главную страницу или обратитесь в службу поддержки.
        </p>
        <div className="mt-1 flex flex-wrap justify-center gap-3">
          <Link to="/" className="btn-primary">На главную</Link>
          <Link to="/support" className="btn-ghost">Служба поддержки</Link>
          {demoUi && <Link to="/demo" className="btn-ghost">Демо для жюри</Link>}
        </div>
      </div>
    </main>
  );
}

function ServerErrorPage() {
  const demoUi = useDemoUi();
  return (
    <main id="main" tabIndex={-1} className="flex min-h-screen flex-col items-center justify-center bg-[#FAF8FC] px-4 py-10 text-center outline-none" data-testid="server-error-page">
      <div className="mx-auto flex w-full max-w-lg flex-col items-center gap-4 rounded-3xl border border-brand-night/10 bg-white p-7 shadow-sm sm:p-9">
        <div className="inline-flex items-center gap-2.5 text-sm font-extrabold text-brand-night">
          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="#0E1126" />
            <circle cx="12.5" cy="16" r="7" fill="none" stroke="#DCE2FF" strokeWidth="2.5" />
            <circle cx="19.5" cy="16" r="7" fill="none" stroke="#EC1D35" strokeWidth="2.5" />
          </svg>
          <span>Драфт</span>
          <span className="rounded-full bg-brand-blush/80 px-2.5 py-0.5 font-mono text-xs font-extrabold text-brand-night">500</span>
        </div>
        <p className="text-5xl font-extrabold text-brand sm:text-6xl" aria-hidden="true">500</p>
        <h1 className="text-xl font-extrabold text-brand-night sm:text-2xl">Внутренняя ошибка страницы</h1>
        <p className="max-w-md text-sm leading-relaxed text-brand-ink/75">
          При обработке запроса возникла непредвиденная ошибка. Введённые данные сохранены — обновите страницу, проверьте состояние сервиса или напишите в поддержку.
        </p>
        <div className="mt-1 flex flex-wrap justify-center gap-3">
          <button type="button" onClick={hardReload} className="btn-primary">Обновить страницу</button>
          <Link to="/" className="btn-ghost">На главную</Link>
          <Link to="/support" className="btn-ghost">Служба поддержки</Link>
          <a href="/status" className="btn-ghost">Состояние сервиса</a>
          {demoUi && <Link to="/demo" className="btn-ghost">Демо для жюри</Link>}
        </div>
      </div>
    </main>
  );
}
