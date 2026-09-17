import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import "./styles.css";
import Activate from "./pages/Activate";
import ErrorPage from "./pages/Error";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Mfa from "./pages/Mfa";

/**
 * Five routes, one per state the interaction API can be in.
 *
 * The `uid` travels in the query string rather than in storage, which is the
 * shape `/authorize` already redirects into at B2 (§8 step 7). Consent becomes
 * a sixth route here and nothing else moves.
 */
// One of the campus photos in public/background, per page load.
// ponytail: the count is literal — bump it when a fifth photo lands.
document.body.style.setProperty("--bg", `url(/background/img_${1 + Math.floor(Math.random() * 4)}.jpeg)`);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/mfa" element={<Mfa />} />
        <Route path="/activer" element={<Activate />} />
        <Route path="/accueil" element={<Home />} />
        <Route path="/erreur" element={<ErrorPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
