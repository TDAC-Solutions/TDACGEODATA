import { useRef, useState } from "react";
import {
  parseSpreadsheet,
  type ImportedWorkbook,
  type ImportSuggestions,
  type SpreadsheetProfile,
} from "./fieldApi";
import type { ParsedFieldTableResponse } from "./contracts";

/**
 * Shared file picker for spreadsheet import profiles.
 *
 * The picker owns file selection and progress only. The caller owns the
 * profile-specific result, commit action, and user-facing outcome.
 */

export interface SpreadsheetFilePickerProps {
  onParsed?: (
    workbook: ImportedWorkbook,
    suggestions: ImportSuggestions
  ) => void;
  /**
   * Required to accept CSV. A CSV parses to a single field-data table
   * rather than a workbook, so a caller without this handler cannot commit
   * it and would otherwise hit a dead end after the file is chosen.
   */
  onTableParsed?: (result: ParsedFieldTableResponse) => void;
  onError: (message: string) => void;
  onCleared?: () => void;
  disabled?: boolean;
  label?: string;
  /**
   * Defaults to every supported format. Pass a narrower list when the
   * caller cannot handle the CSV path - a picker with no onTableParsed
   * should not advertise .csv, because selecting one can only fail.
   */
  accept?: string;
  profile?: SpreadsheetProfile;
}

function FileIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M3 2.5A1.5 1.5 0 0 1 4.5 1H9l4 4v8.5A1.5 1.5 0 0 1 11.5 15h-7A1.5 1.5 0 0 1 3 13.5v-11Z"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path d="M9 1v4h4" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export function SpreadsheetFilePicker({
  onParsed,
  onTableParsed,
  onError,
  onCleared,
  disabled = false,
  label = "Import from Excel input sheet",
  accept = ".xlsx,.xlsm,.csv",
  profile = "field",
}: SpreadsheetFilePickerProps) {
  // A CSV can only be committed through onTableParsed. Without that
  // handler, advertising .csv would let the user pick a file that can
  // never be imported, so drop it from the accept list rather than
  // failing after the upload.
  const effectiveAccept = onTableParsed ? accept : accept.replace(/\.csv/gi, "");
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    // Reset the input so selecting the same file twice re-fires the event.
    event.target.value = "";

    if (!file) {
      return;
    }

    try {
      setBusy(true);
      const result = await parseSpreadsheet(file, profile);
      setFileName(file.name);
      if (result.dataset === "field_workbook") {
        onParsed?.(result.workbook, result.suggestions);
      } else {
        if (onTableParsed) {
          onTableParsed(result);
        } else {
          onError(
            "This CSV is a field-data table. Select an existing project location before importing it."
          );
        }
      }
    } catch (error) {
      console.error("Spreadsheet parse failed:", error);
      onError(
        error instanceof Error
          ? error.message
          : "Unable to read this spreadsheet."
      );
    } finally {
      setBusy(false);
    }
  }

  function clearFile() {
    setFileName(null);
    onCleared?.();
  }

  return (
    <div className="excel-import">
      <input
        ref={inputRef}
        type="file"
        accept={effectiveAccept}
        onChange={handleFile}
        disabled={busy || disabled}
        style={{ display: "none" }}
      />

      {fileName && !busy ? (
        <div className="excel-file-chip" role="status">
          <span className="excel-file-name">
            <FileIcon />
            {fileName}
          </span>
          <button
            type="button"
            className="excel-file-remove"
            onClick={clearFile}
            disabled={disabled}
            aria-label={`Remove ${fileName}`}
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M2.5 2.5l7 7m0-7l-7 7"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="btn"
          disabled={busy || disabled}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "Reading spreadsheet..." : label}
        </button>
      )}
    </div>
  );
}
