/* Guards the QR print layout against the bug that chopped every label in
 * half.
 *
 * The defect: `.qr-print-sheet` used `position: absolute; inset: 0` inside
 * @media print. `inset: 0` pins bottom and right as well as top and left, so
 * the sheet's height collapsed to its containing block's -- the viewport. The
 * grid of labels then overflowed a fixed-height box and the paginator cut
 * through it, slicing each QR code across a row boundary. Two further
 * containers compounded it: `.modal` and `.qr-print-modal` both clamp to
 * `max-height: calc(100vh - 48px)`, and in print `100vh` is the page box, so
 * the sheet was clipped to one page regardless of how many samples were
 * selected.
 *
 * Print output cannot be rendered here, so this asserts the properties that
 * produced the bug stay absent. A visual check is still worth doing once by
 * hand after changing this block.
 */
import { readFileSync } from "node:fs";

const css = readFileSync("src/shell.css", "utf8");

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);

/** Pull out the @media print block that governs the QR sheet. */
function printBlock() {
  const start = css.indexOf("@media print");
  if (start === -1) return "";
  let depth = 0;
  let opened = false;
  for (let i = start; i < css.length; i++) {
    if (css[i] === "{") {
      depth++;
      opened = true;
    } else if (css[i] === "}") {
      depth--;
      if (opened && depth === 0) return css.slice(start, i + 1);
    }
  }
  return css.slice(start);
}

const block = printBlock();
check("found a @media print block", block.length > 0);
check("the print block covers the QR sheet", block.includes(".qr-print-sheet"));

// Isolate the .qr-print-sheet rule itself within the print block.
function rule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = block.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, "s"));
  return match ? match[1] : "";
}

const sheet = rule(".qr-print-sheet");
check("print rule for .qr-print-sheet found", sheet.length > 0);

check(
  "sheet is NOT pinned with inset:0 (that collapses its height)",
  !/inset\s*:\s*0\s*;/.test(sheet)
);
check(
  "sheet keeps height auto rather than being sized by the viewport",
  !/height\s*:\s*100vh/.test(sheet)
);
check(
  "sheet is still taken out of flow so the hidden app cannot offset it",
  /position\s*:\s*absolute/.test(sheet)
);
check(
  "sheet is anchored to the top-left of the page",
  /top\s*:\s*0/.test(sheet) && /left\s*:\s*0/.test(sheet)
);

// The two clamping containers must be neutralised inside the print block.
const modalRule = block.match(/\.modal,\s*\.qr-print-modal\s*\{([^}]*)\}/s);
check("print rule neutralising the modal containers found", !!modalRule);
const modalBody = modalRule ? modalRule[1] : "";
check(
  "modal max-height is cleared for print",
  /max-height\s*:\s*none/.test(modalBody)
);
check(
  "modal overflow is cleared for print",
  /overflow\s*:\s*visible/.test(modalBody)
);

// The backdrop is the sheet's containing block; leaving it fixed is fine only
// because the sheet no longer derives its height from it. Confirm it is
// still addressed so the two cannot drift apart silently.
check(
  "backdrop is handled in the print block",
  block.includes(".modal-backdrop")
);

// A label, and the QR inside it, must stay whole across a page break.
const card = rule(".qr-print-card");
check(
  "card avoids breaking across pages",
  /break-inside\s*:\s*avoid/.test(card)
);
check(
  "QR image avoids breaking across pages",
  /\.qr-print-card img\s*\{[^}]*break-inside\s*:\s*avoid/.test(block)
);

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);