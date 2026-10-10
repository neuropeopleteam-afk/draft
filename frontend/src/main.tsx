import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, useLocation } from "react-router-dom";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AuthProvider } from "./lib/auth";
import { MetaProvider } from "./lib/meta";
import "./index.css";
import { registerPwa } from "./integrations/pwa";

registerPwa();

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
    <BrowserRouter>
      <MetaProvider>
        <AuthProvider>
          <Guarded />
        </AuthProvider>
      </MetaProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
