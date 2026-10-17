import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { changePassword } from "../api/auth";
import { setTokens } from "../api/token";
import { ADMIN_USERS, LOGIN } from "../routes";
import { useUnsavedGuard } from "../pages/ProjectWorkspace/UnsavedChanges";

const TITLES: Record<string, string> = {
  "/": "Portfolio Centre",
  "/projects/new": "Add New Project",
};

function topTitle(pathname: string): string {
  if (pathname.startsWith("/project/")) return "Project Workspace";
  return TITLES[pathname] ?? "TDAC AGS Console";
}

function initials(username: string): string {
  return username
    .split(/\s+/)
    .map((part) => part[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function Topbar() {
  const confirmDiscard = useUnsavedGuard();
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logoutUser } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [changePwOpen, setChangePwOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Search writes ?q= on the portfolio route, which is the only surface
  // that can filter. Searching from the workspace therefore navigates
  // there with the term applied rather than silently doing nothing.
  const [searchParams, setSearchParams] = useSearchParams();
  const [searchValue, setSearchValue] = useState(searchParams.get("q") ?? "");

  useEffect(() => {
    setSearchValue(searchParams.get("q") ?? "");
  }, [searchParams]);

  function handleSearchSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = searchValue.trim();

    if (location.pathname !== "/") {
      // Leaving the workspace unmounts it, discarding anything half-entered
      // on the SPT grid or a lab revision. This used to ask unconditionally,
      // because there was no way to know whether anything was actually
      // unsaved -- so it nagged on searches that risked nothing. The shared
      // registry in App makes the real question answerable now.
      if (!confirmDiscard()) return;

      navigate(`/?q=${encodeURIComponent(trimmed)}`);
      return;
    }

    if (trimmed) {
      setSearchParams({ q: trimmed });
    } else {
      setSearchParams({});
    }
  }

  // Close the account menu on outside click or Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  async function handleLogout() {
    // Logging out leaves the workspace with its grid still mounted. Ask
    // before that, or the rows are gone and the session with them.
    if (!confirmDiscard()) return;
    await logoutUser();
    navigate(LOGIN, { replace: true });
  }

  // Password change keeps this session alive: the fresh token pair the
  // server returns replaces the stored one, while every other session is
  // revoked by the token generation bump.
  async function handleChangePassword(
    current: string,
    next: string,
    confirm: string
  ) {
    const result = await changePassword(current, next, confirm);
    setTokens(result.access_token, result.refresh_token);
  }

  return (
    <header className="topbar">
      <h2 className="topbar-title"><b>TDAC</b> / {topTitle(location.pathname)}</h2>
      <div className="topbar-right">
      <form
        className="search topbar-search"
        role="search"
        onSubmit={handleSearchSubmit}
      >
        <input
          type="search"
          placeholder="Search projects..."
          aria-label="Search projects"
          value={searchValue}
          onChange={(event) => setSearchValue(event.target.value)}
        />
      </form>
        {user?.role === "admin" && (
          <button
            type="button"
            className="btn"
            onClick={() => {
              // User Management is a different route; it unmounts the
              // workspace exactly as the search above does.
              if (!confirmDiscard()) return;
              navigate(ADMIN_USERS);
            }}
          >
            User Management
          </button>
        )}
      {/* Help removed: there is no help destination or documentation URL
          behind it. A dead button reads as broken. Reinstate when one
          exists. */}
        {user ? (
          <div className="account-menu" ref={menuRef}>
            <button
              type="button"
              className="topbar-user account-trigger"
              onClick={() => setMenuOpen((o) => !o)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <span className="avatar">{initials(user.username)}</span>
              <span className="topbar-user-name">{user.username}</span>
              <span className="chip chip-muted">{user.role}</span>
            </button>
            {menuOpen && (
              <div className="account-dropdown" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  className="account-item"
                  onClick={() => {
                    setMenuOpen(false);
                    setChangePwOpen(true);
                  }}
                >
                  Change password
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="account-item account-item-danger"
                  onClick={() => {
                    setMenuOpen(false);
                    handleLogout();
                  }}
                >
                  Sign out of all devices
                </button>
              </div>
            )}
          </div>
        ) : null}
      </div>
      {changePwOpen && (
        <ChangePasswordModal
          onChangePassword={handleChangePassword}
          onClose={() => setChangePwOpen(false)}
        />
      )}
    </header>
  );
}

function ChangePasswordModal({
  onChangePassword,
  onClose,
}: {
  onChangePassword: (current: string, next: string, confirm: string) => Promise<void>;
  onClose: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [busy, setBusy] = useState(false);
  const currentRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    currentRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const match = next.length > 0 && next === confirm;
  const mismatch = confirm.length > 0 && next !== confirm;
  const valid = current.length > 0 && next.length >= 8 && match;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onChangePassword(current, next, confirm);
      setSuccess(true);
      setTimeout(onClose, 1200);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Password change failed"
      );
      setBusy(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="change-pw-title">
        <div className="panel-head">
          <h2 className="panel-title" id="change-pw-title">
            Change password
          </h2>

          <button
            type="button"
            className="btn"
            onClick={onClose}
            aria-label="Close"
            disabled={busy}
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path
                d="M2.5 2.5l7 7m0-7l-7 7"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        {success ? (
          <p className="pw-success">Password changed. Your other sessions were signed out.</p>
        ) : (
          <form onSubmit={submit} className="pw-form">
            <div className="panel-body">
              {error && <div className="warning-note">{error}</div>}

              <label>
                <span className="eyebrow">CURRENT PASSWORD</span>
                <input
                  ref={currentRef}
                  className="modal-input"
                  type="password"
                  autoComplete="current-password"
                  value={current}
                  onChange={(e) => setCurrent(e.target.value)}
                  disabled={busy}
                />
              </label>

              <label>
                <span className="eyebrow">NEW PASSWORD</span>
                <input
                  className="modal-input"
                  type="password"
                  autoComplete="new-password"
                  value={next}
                  onChange={(e) => setNext(e.target.value)}
                  disabled={busy}
                  minLength={8}
                />
              </label>

              <label>
                <span className="eyebrow">CONFIRM NEW PASSWORD</span>
                <input
                  className="modal-input"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  disabled={busy}
                  aria-invalid={mismatch}
                />
              </label>

              <div className="pw-match" aria-live="polite">
                {mismatch && <span className="pw-match-err">Passwords do not match</span>}
                {match && <span className="pw-match-ok">Passwords match</span>}
                {next.length > 0 && next.length < 8 && (
                  <span className="pw-match-err">At least 8 characters</span>
                )}
              </div>

              <div className="actions">
                <button
                  type="button"
                  className="btn"
                  onClick={onClose}
                  disabled={busy}
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={!valid || busy}
                >
                  {busy ? "Changing..." : "Change password"}
                </button>
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
