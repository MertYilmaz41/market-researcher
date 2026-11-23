// Colors for JS (score scale, map, charts). The values live in style.css :root only;
// this module just reads them (at call time, so a theme switch shows at once), so a palette change
// never touches the JS.

const root = getComputedStyle(document.documentElement);
export const cssVar = (name) => root.getPropertyValue(name).trim();

// The score's three steps, as in the pills: violet 67+, near-white 42+, gray under ("none": no score yet, or too
// few similar games). Since #12 the score is the similar games' hit rate / 25%, so 67 and 42 are hit rates of
// ~17% and ~10.5%: about the top tenth and top two-fifths of games with 100+ reviews (scoring.verdict uses them).
// Before: 65/45 (map 30) with fixability, 56/35 (map 20), 67/42 with the dissatisfaction floor (#6, #7).
export const scoreLevel = (score) => (score == null ? "none" : score >= 67 ? "hi" : score >= 42 ? "mid" : "lo");
export const scoreColor = (score) => cssVar(`--score-${scoreLevel(score)}`);

// The map's bubbles: four steps from gray to violet (30 is a ~7.5% hit rate, about the bottom third).
export const mapColor = (score) => cssVar(`--map-${score == null ? 0 : score >= 67 ? 3 : score >= 42 ? 2 : score >= 30 ? 1 : 0}`);
