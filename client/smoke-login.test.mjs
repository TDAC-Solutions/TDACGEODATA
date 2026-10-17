/* Runtime smoke test for the LOGIN page against the REAL backend:
   boots the real App at /login with NO token, types admin/admin@123 into
   the real form, submits it, and verifies the app lands on the portfolio
   home page with the session stored. The fetch layer is NOT mocked here:
   every request goes to the live uvicorn on 127.0.0.1:8000, so this
   proves the exact credentials the user will type. */
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", {
  url: "http://localhost/#/login",
  pretendToBeVisual: true,
});
global.window = dom.window;
global.document = dom.window.document;
Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });
global.HTMLElement = dom.window.HTMLElement;
global.IS_REACT_ACT_ENVIRONMENT = true;
global.localStorage = dom.window.localStorage;

const fs = await import("node:fs");
const tokenSrc = fs.readFileSync("src/api/token.ts", "utf8");
const keyMatch = tokenSrc.match(/ACCESS_TOKEN_KEY\s*=\s*["']([^"']+)["']/)
  || tokenSrc.match(/(?:getItem|setItem|removeItem)\(\s*["']([^"']+)["']/);
if (!keyMatch) {
  console.log("AUTH STORAGE KEY NOT FOUND");
  process.exit(2);
}
const KEY = keyMatch[1];

const { createRoot } = await import("react-dom/client");
const { act, StrictMode } = await import("react");
const React = await import("react");
const { default: App } = await import("./src/App.tsx");
const { AuthProvider } = await import("./src/auth/AuthContext.tsx");

const root = createRoot(document.getElementById("root"));
await act(async () => {
  root.render(
    React.createElement(StrictMode, null,
      React.createElement(AuthProvider, null, React.createElement(App)))
  );
});
await act(async () => { await new Promise((r) => setTimeout(r, 120)); });

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);

// 1. Login form actually rendered (username + password + submit)
const inputs = [...document.querySelectorAll("input")];
const userInput = document.getElementById("username");
const passInput = document.getElementById("password");
const form = document.querySelector("form");
check("login form rendered", !!form && !!userInput && !!passInput);

// 2. Type the real credentials into the real inputs
const setNative = (el, value) => {
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
  setter.call(el, value);
  el.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
};
await act(async () => {
  setNative(userInput, "admin");
  setNative(passInput, "admin@123");
});
check("credentials typed", userInput.value === "admin" && passInput.value === "admin@123");

// 3. Submit -> real POST /api/auth/login runs against live uvicorn
await act(async () => {
  form.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
  await new Promise((r) => setTimeout(r, 2500));
});

// 4. Session stored + app moved past the login page
const stored = dom.window.localStorage.getItem(KEY);
check("access token stored after login", !!stored && stored.length > 20);

const stillOnLogin = document.querySelector("#username") !== null;
check("navigated away from login page", !stillOnLogin);

// 5. Whatever page rendered now shows authenticated content, not an error
const bodyText = document.body.textContent || "";
check("no error message on screen", !/invalid|failed|error/i.test(bodyText));

for (const line of results) console.log(line);
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(failed.length === 0 ? "ALL PASS" : `${failed.length} FAILED`);
process.exit(failed.length === 0 ? 0 : 1);
