export const VALUE_LABELS = {
  allowed: "Allowed",
  allowed_with_conditions: "With conditions",
  prohibited: "Prohibited",
  not_stated: "Not stated",
  yes: "Required",
  partial: "Partly",
  no: "Not required",
  unknown: "No data",
};

export const VALUE_TONE = {
  allowed: "ok",
  allowed_with_conditions: "warn",
  prohibited: "bad",
  yes: "warn",
  partial: "warn",
  no: "ok",
  not_stated: "none",
  unknown: "none",
};

export const COLUMNS = [
  ["author_use", "Author use"],
  ["disclosure_required", "Disclosure"],
  ["ai_as_author", "AI as author"],
  ["ai_images", "AI images"],
  ["reviewer_use", "Reviewer use"],
  ["reviewer_upload", "Reviewer upload"],
  ["editor_use", "Editor use"],
];

export const LEVEL_LABELS = { publisher: "Publisher", society: "Society", journal: "Journal" };

export const fmtDate = (d) =>
  d ? new Date(d + (d.length === 10 ? "T00:00:00Z" : "")).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "–";
