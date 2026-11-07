// Colors for JS (score scale, 3D map, charts). The values live in style.css :root only;
// this module just reads them (at call time, so a theme switch shows at once), so a palette change
// never touches the JS.

const root = getComputedStyle(document.documentElement);
export const cssVar = (name) => root.getPropertyValue(name).trim();

// The score's three steps, as in the pills: violet 65+, near-white 45+, gray under.
export const scoreLevel = (score) => (score >= 65 ? "hi" : score >= 45 ? "mid" : "lo");
export const scoreColor = (score) => cssVar(`--score-${scoreLevel(score)}`);

// The map's bubbles: four steps from gray to violet.
export const mapColor = (score) => cssVar(`--map-${score >= 65 ? 3 : score >= 45 ? 2 : score >= 30 ? 1 : 0}`);
