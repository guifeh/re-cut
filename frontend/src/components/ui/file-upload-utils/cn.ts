type ClassValue = string | number | null | boolean | undefined | ClassValue[] | Record<string, boolean | undefined | null>;

function clsx(...inputs: ClassValue[]): string {
  const out: string[] = [];
  for (const input of inputs) {
    if (!input) continue;
    if (typeof input === "string" || typeof input === "number") {
      out.push(String(input));
    } else if (Array.isArray(input)) {
      const nested = clsx(...input);
      if (nested) out.push(nested);
    } else if (typeof input === "object") {
      for (const key in input) {
        if (input[key]) out.push(key);
      }
    }
  }
  return out.join(" ");
}

/**
 * Merge conditional class names. Dedupe conflicting Tailwind utilities
 * sharing the same "ui-" prefixed property group (last one wins), without
 * requiring the tailwind-merge package as a runtime dependency.
 */
export function cn(...inputs: ClassValue[]) {
  const merged = clsx(...inputs);
  const classes = merged.split(/\s+/).filter(Boolean);
  const seen = new Map<string, number>();
  classes.forEach((cls, i) => seen.set(cls, i));
  // Preserve first-seen order but let later duplicates win (simple last-wins
  // de-dupe); this is sufficient for this component's static class lists.
  const result: string[] = [];
  const added = new Set<string>();
  for (let i = classes.length - 1; i >= 0; i--) {
    const cls = classes[i];
    if (!added.has(cls)) {
      added.add(cls);
      result.unshift(cls);
    }
  }
  return result.join(" ");
}
