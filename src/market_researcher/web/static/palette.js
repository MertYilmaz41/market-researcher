// Colors for JS (score scale, map, charts). The values live in style.css :root only;
// this module just reads them (at call time, so a theme switch shows at once), so a palette change
// never touches the JS.

const root = getComputedStyle(document.documentElement);
export const cssVar = (name) => root.getPropertyValue(name).trim();

// The score's three steps, as in the pills: violet 56+, near-white 35+, gray under. They were 65/45 (map 30) while
// fixability was in the score; these are the same games' scores without it (old^(4/3) / 100^(1/3)).
export const scoreLevel = (score) => (score >= 56 ? "hi" : score >= 35 ? "mid" : "lo");
export const scoreColor = (score) => cssVar(`--score-${scoreLevel(score)}`);

// The map's bubbles: four steps from gray to violet.
export const mapColor = (score) => cssVar(`--map-${score >= 56 ? 3 : score >= 35 ? 2 : score >= 20 ? 1 : 0}`);
