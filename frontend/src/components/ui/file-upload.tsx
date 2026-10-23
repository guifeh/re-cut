import * as React from "react";
import { cn } from "./file-upload-utils/cn";
import { useUiContent } from "./file-upload-utils/content";
import { useUiId } from "./file-upload-utils/hooks";

export interface FileUploadProps {
  label?: string;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  files: File[];
  onFilesChange: (files: File[]) => void;
  /** Max size per file in bytes; oversized files are rejected and omitted. */
  maxSizeBytes?: number;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * FileUpload — drag-and-drop zone plus a browse button (always present, so
 * drag-and-drop is never the *only* way to select files). Files are fully
 * controlled: the component reports changes via `onFilesChange` rather than
 * owning selection state itself, so consumers can validate/upload freely.
 *
 * NOTE: this ports the upstream `@ui-system/ui` implementation, which
 * styles itself with a custom "ui-" prefixed Tailwind build backed by CSS
 * custom properties (see styles/index.css). That prefixed utility set isn't
 * available at render time here, so this file uses plain Tailwind
 * utilities wired to the SAME `--ui-*` custom properties — same tokens,
 * same visual result, no dependency on a bespoke prefixed build.
 */
export function FileUpload({
  label,
  accept,
  multiple,
  disabled,
  files,
  onFilesChange,
  maxSizeBytes,
}: FileUploadProps) {
  const content = useUiContent();
  const inputId = useUiId("file-upload");
  const [isDragging, setIsDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  function addFiles(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list).filter(
      (f) => !maxSizeBytes || f.size <= maxSizeBytes,
    );
    onFilesChange(multiple ? [...files, ...incoming] : incoming.slice(0, 1));
  }

  function removeFile(index: number) {
    onFilesChange(files.filter((_, i) => i !== index));
  }

  return (
    <div className="flex flex-col gap-2">
      {label && (
        <span className="text-sm font-medium" style={{ color: "var(--ui-fg)" }}>
          {label}
        </span>
      )}
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (!disabled) addFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed p-8 text-center transition-colors focus-visible:outline-none",
          disabled && "cursor-not-allowed opacity-50",
        )}
        style={{
          borderColor: isDragging
            ? "var(--ui-primary)"
            : "var(--ui-border-strong)",
          backgroundColor: isDragging ? "var(--ui-bg-subtle)" : "transparent",
          boxShadow: "none",
        }}
      >
        <p className="text-sm" style={{ color: "var(--ui-fg-muted)" }}>
          {content.fileUpload.dragPrompt}{" "}
          <span className="font-medium" style={{ color: "var(--ui-primary)" }}>
            {content.fileUpload.browse}
          </span>
        </p>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          onChange={(e) => addFiles(e.target.files)}
          style={{
            position: "absolute",
            width: 1,
            height: 1,
            padding: 0,
            margin: -1,
            overflow: "hidden",
            clip: "rect(0,0,0,0)",
            whiteSpace: "nowrap",
            border: 0,
          }}
        />
      </div>
      {files.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {files.map((file, i) => (
            <li
              key={`${file.name}-${i}`}
              className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
              style={{ borderColor: "var(--ui-border)" }}
            >
              <span className="truncate" style={{ color: "var(--ui-fg)" }}>
                {file.name}
              </span>
              <span
                className="shrink-0 text-xs"
                style={{ color: "var(--ui-fg-muted)" }}
              >
                {formatBytes(file.size)}
              </span>
              <button
                type="button"
                onClick={() => removeFile(i)}
                aria-label={`${content.fileUpload.remove}: ${file.name}`}
                className="shrink-0 rounded p-1 transition-colors focus-visible:outline-none"
                style={{ color: "var(--ui-fg-muted)" }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.backgroundColor =
                    "var(--ui-bg-subtle)")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.backgroundColor = "transparent")
                }
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 12 12"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M3 3L9 9M9 3L3 9"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default FileUpload;
