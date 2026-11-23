// Colors for JS (score scale, map, charts). The values live in style.css :root only;
// this module just reads them (at call time, so a theme switch shows at once), so a palette change
// never touches the JS.

const root = getComputedStyle(document.documentElement);
export const cssVar = (name) => root.getPropertyValue(name).trim();

// The score's three steps, as in the pills: violet 67+, near-white 42+, gray under. They were 65/45 (map 30) while
// fixability was in the score, then 56/35 (map 20) until the dissatisfaction floor (#6, #7) lifted every score
// under 70% positive; each was moved to keep the most games in their band (100-100k reviews x 5-70%: 88-95%).
// Liked games (70%+) reach ~52 at most: near-white, never violet.
export const scoreLevel = (score) => (score >= 67 ? "hi" : score >= 42 ? "mid" : "lo");
export const scoreColor = (score) => cssVar(`--score-${scoreLevel(score)}`);

// The map's bubbles: four steps from gray to violet.
export const mapColor = (score) => cssVar(`--map-${score >= 67 ? 3 : score >= 42 ? 2 : score >= 30 ? 1 : 0}`);
