import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AppErrorBoundary, BootMark } from "./components/Boot";
import { AuthProvider } from "./lib/auth";
import { MetaProvider } from "./lib/meta";
import "./index.css";
import { registerPwa } from "./integrations/pwa";

// Я16: код приложения загрузился и выполняется — сторож index.html убирает метку повтора ?r= из адреса
window.__fspBoot?.started();
registerPwa();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* Я16: что бы ни упало при отрисовке — понятный экран с «Обновить», а не пустой root */}
    <AppErrorBoundary>
      <BrowserRouter>
        <MetaProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </MetaProvider>
      </BrowserRouter>
    </AppErrorBoundary>
    <BootMark />
  </React.StrictMode>,
);
