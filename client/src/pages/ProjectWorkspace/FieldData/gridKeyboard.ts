/**
 * Keyboard helpers shared by the Field Data entry grids.
 *
 * Both grids let Left/Right stay sideways so a value already keyed can be
 * corrected with the caret, and only take over as navigation once the caret
 * has run out of room. That needs to know where the caret is.
 *
 * <input type="number"> does not expose selectionStart/selectionEnd -- they
 * are null, not 0 -- so a check written as `selectionStart === 0` is never
 * true on them. Every numeric cell in both grids is type="number", which
 * means Left and Right silently did nothing at all in both, while Tab, Enter
 * and Up/Down worked and hid the problem.
 *
 * For a numeric input the caret only has anywhere to go while the value is
 * longer than one character, so a single character counts as being at both
 * ends. Empty already counts as being at both ends in any input type.
 */

type CaretInput = HTMLInputElement | HTMLTextAreaElement;

export function caretAtStart(el: CaretInput): boolean {
  const value = el.value ?? "";
  if (value === "") return true;
  // null means the input type has no selection API at all (number, email...).
  if (el.selectionStart === null || el.selectionEnd === null) {
    return value.length <= 1;
  }
  return el.selectionStart === 0 && el.selectionEnd === 0;
}

export function caretAtEnd(el: CaretInput): boolean {
  const value = el.value ?? "";
  if (value === "") return true;
  if (el.selectionStart === null || el.selectionEnd === null) {
    return value.length <= 1;
  }
  return (
    el.selectionStart === value.length && el.selectionEnd === value.length
  );
}