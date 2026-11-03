"use client";

import { useSyncExternalStore } from "react";

const root = () => document.documentElement;
const isNight = () => {
  const attr = root().getAttribute("data-theme");
  return attr ? attr === "night" : window.matchMedia("(prefers-color-scheme: dark)").matches;
};
const subscribe = (cb: () => void) => {
  const mo = new MutationObserver(cb);
  mo.observe(root(), { attributes: true, attributeFilter: ["data-theme"] });
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", cb);
  return () => {
    mo.disconnect();
    mq.removeEventListener("change", cb);
  };
};

export function ThemeToggle() {
  const night = useSyncExternalStore(subscribe, isNight, () => false);
  const toggle = () => {
    const next = night ? "day" : "night";
    root().setAttribute("data-theme", next);
    try { localStorage.setItem("arena-theme", next); } catch { /* storage unavailable */ }
  };
  return (
    <button type="button" onClick={toggle} aria-pressed={night} aria-label="Switch between Day and Night edition">
      {night ? "DAY / •NIGHT" : "•DAY / NIGHT"}
    </button>
  );
}
