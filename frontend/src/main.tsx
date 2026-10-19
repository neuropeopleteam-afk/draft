import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, useLocation } from "react-router-dom";
import App from "./App";
import { AppErrorBoundary, BootMark } from "./components/Boot";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AuthProvider } from "./lib/auth";
import { MetaProvider } from "./lib/meta";
import "./index.css";
import { registerPwa } from "./integrations/pwa";
import { currentTheme } from "./lib/theme";

// Я16: код приложения загрузился и выполняется — сторож index.html убирает метку повтора ?r= из адреса
window.__fspBoot?.started();
registerPwa();
// W2: тема публичных страниц — до первой отрисовки, без вспышки другой темы
document.documentElement.dataset.theme = currentTheme();

/** Ошибка отрисовки внутри приложения снимается переходом по меню (resetKey — адрес страницы, docs/LOAD.md). */
function Guarded() {
  const { pathname } = useLocation();
  return (
    <ErrorBoundary resetKey={pathname}>
      <App />
    </ErrorBoundary>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* Я16: что бы ни упало и где бы (маршрутизатор, провайдеры) — понятный экран с «Обновить», а не пустой root */}
    <AppErrorBoundary>
      <BrowserRouter>
        <MetaProvider>
          <AuthProvider>
            <Guarded />
          </AuthProvider>
        </MetaProvider>
      </BrowserRouter>
    </AppErrorBoundary>
    <BootMark />
  </React.StrictMode>,
);
