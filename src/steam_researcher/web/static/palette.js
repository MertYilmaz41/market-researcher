// Colors for JS (score scale, 3D map, charts). The values live in style.css :root only;
// this module just reads them, so a palette change never touches the JS.

const root = getComputedStyle(document.documentElement);
export const cssVar = (name) => root.getPropertyValue(name).trim();

const hexToRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const rgbToHex = (rgb) => `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`;
const SCORE_STOPS = [0, 1, 2, 3, 4].map((i) => hexToRgb(cssVar(`--score-${i}`)));

// Opportunity score 0..100 -> hex color along the --score-0..4 scale (blue -> teal -> gold).
export function scoreColor(score) {
  const t = (Math.max(0, Math.min(100, score)) / 100) * (SCORE_STOPS.length - 1);
  const i = Math.min(Math.floor(t), SCORE_STOPS.length - 2);
  const [a, b] = [SCORE_STOPS[i], SCORE_STOPS[i + 1]];
  return rgbToHex(a.map((c, k) => c + (b[k] - c) * (t - i)));
}

// WCAG relative luminance and contrast ratio.
const luminance = (hex) => {
  const [r, g, b] = hexToRgb(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (x, y) => {
  const [hi, lo] = [luminance(x), luminance(y)].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
};

// Text color for something filled with scoreColor(score): black or white, whichever reads better.
// Pure black/white (not --bg/--text): mid-tone scores only reach WCAG 4.5:1 with these.
export function scoreInk(score) {
  const fill = scoreColor(score);
  return contrast(fill, "#000000") >= contrast(fill, "#ffffff") ? "#000000" : "#ffffff";
}
