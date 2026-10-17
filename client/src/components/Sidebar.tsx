import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";
import { HOME } from "../routes";

function  IconPortfolio() {
  return(
    <svg viewBox = "0 0 16 16" fill = "none" stroke = "currentColor" strokeWidth = "1.7" aria-hidden = "true">
      <path d = "M2 5.5h12v8H2z"/>
      <path d = "M5.5 5.5V4a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 10.5 4v1.5" />
    </svg>
  );
}

function IconMark() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <ellipse cx="8" cy="4.6" rx="4.6" ry="1.8" />
      <path d="M3.4 4.6v6.8c0 1 2.1 1.8 4.6 1.8s4.6-.8 4.6-1.8V4.6" />
      <path d="M3.4 8c0 1 2.1 1.8 4.6 1.8S12.6 9 12.6 8" />
    </svg>
  );
}

interface NavEntry {
  to: string;
  label: string;
  icon: ReactNode;
  end?: boolean;
}

const NAV: NavEntry[] = [
  { to: HOME, label: "Portfolio Centre", icon: <IconPortfolio />, end: true },
];

export function Sidebar() {
  return (
    <aside className="sidebar" aria-label="Main navigation">
      <div className="sidebar-brand">
        <span className="sidebar-brand-mark">
          <IconMark />
        </span>
        <span>
          <div className="sidebar-brand-name">TDAC GeoData</div>
          <div className="sidebar-brand-sub">Integrated Platform</div>
        </span>
      </div>

      <nav className="sidebar-nav">
        <div className="nav-section">Workspace</div>
        {NAV.map((entry) => (
          <NavLink
            key={entry.to}
            to={entry.to}
            end={entry.end}
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          >
            {entry.icon}
            {entry.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <span>TDAC Foundation Tools</span>
        {/* <span>AGS 4.2 · postgres</span>  */}
      </div>
    </aside>
  );
}
