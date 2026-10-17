import type { AnnotationMode, ApplyOptions, FormMode, GraphicsMode, ImageMode, SanitizeOptions } from "../types";

/** Choices in the apply dialog, remembered between sessions. */
export interface ApplySettings {
  images: ImageMode;
  graphics: GraphicsMode;
  removeHidden: boolean;
  sanitize: SanitizeOptions;
}

export const DEFAULT_SANITIZE: SanitizeOptions = {
  metadata: true,
  annotations: "remove",
  forms: "flatten",
  attachments: true,
  links: true,
  javascript: true,
  thumbnails: true,
  bookmarks: false,
  pageLabels: false,
  layers: true,
  outsideCrop: true,
  hiddenText: true,
  keepOcrText: true,
};

export const DEFAULT_SETTINGS: ApplySettings = {
  images: "pixels",
  graphics: "covered",
  removeHidden: true,
  sanitize: DEFAULT_SANITIZE,
};

const IMAGE_MODES: readonly ImageMode[] = ["pixels", "remove", "none"];
const GRAPHICS_MODES: readonly GraphicsMode[] = ["covered", "touched", "none"];
const ANNOTATION_MODES: readonly AnnotationMode[] = ["remove", "flatten", "keep"];
const FORM_MODES: readonly FormMode[] = ["flatten", "reset", "keep"];

function pick<T>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

/** Settings from untrusted saved data, with defaults for anything missing or invalid. */
export function parseSettings(saved: unknown): ApplySettings {
  const s = (saved && typeof saved === "object" ? saved : {}) as Record<string, unknown>;
  const raw = (s.sanitize && typeof s.sanitize === "object" ? s.sanitize : {}) as Record<string, unknown>;
  const sanitize = { ...DEFAULT_SANITIZE };
  for (const key of Object.keys(DEFAULT_SANITIZE) as (keyof SanitizeOptions)[]) {
    if (key === "annotations") sanitize.annotations = pick(raw.annotations, ANNOTATION_MODES, sanitize.annotations);
    else if (key === "forms") sanitize.forms = pick(raw.forms, FORM_MODES, sanitize.forms);
    else sanitize[key] = flag(raw[key], sanitize[key]);
  }
  return {
    images: pick(s.images, IMAGE_MODES, DEFAULT_SETTINGS.images),
    graphics: pick(s.graphics, GRAPHICS_MODES, DEFAULT_SETTINGS.graphics),
    removeHidden: flag(s.removeHidden, DEFAULT_SETTINGS.removeHidden),
    sanitize,
  };
}

/** The request options; with no marks only hidden information is removed. */
export function applyOptions(settings: ApplySettings, markCount: number): ApplyOptions {
  const { images, graphics, removeHidden, sanitize } = settings;
  return { images, graphics, sanitize: removeHidden || markCount === 0 ? sanitize : null };
}

export function isDefaultSanitize(sanitize: SanitizeOptions): boolean {
  return (Object.keys(DEFAULT_SANITIZE) as (keyof SanitizeOptions)[]).every(
    (k) => sanitize[k] === DEFAULT_SANITIZE[k],
  );
}

const STORAGE_KEY = "pdf-redact-apply";

export function loadSettings(): ApplySettings {
  try {
    return parseSettings(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null"));
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: ApplySettings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* storage unavailable */
  }
}
