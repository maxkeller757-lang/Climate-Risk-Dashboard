import type { LayerMeta } from "./api";

export type ColorStop = [number, string];

// Per-category overrides of the default 2-stop (light -> category color)
// ramp, for categories where that default doesn't give enough visual
// separation at the high end. Wildfire: arid-West ZCTAs near 100 (e.g.
// Flagstaff AZ ~99.9) were reading as barely darker than medium-risk
// Southeast ZCTAs around 60-70 (e.g. Columbia SC ~63) under linear
// interpolation to a single end color, since that mid-range score is
// already 60-70% of the way to full saturation. Adding a third stop lets
// 0-70 keep the same light-to-"normal red" ramp while 70-100 ramps on into
// a visibly darker red, so only genuinely extreme risk reads as deep red.
const CATEGORY_COLOR_STOPS: Record<string, ColorStop[]> = {
  wildfire: [
    [0, "#f5f5f5"],
    [70, "#D32F2F"],
    [100, "#6B0000"],
  ],
  // Smog ramp: clear air -> haze -> soot. Three stops for the same reason
  // wildfire needs them -- a plain light-to-grey interpolation leaves the
  // worst areas barely distinguishable from mid-range ones.
  air_quality: [
    [0, "#f7f7f6"],
    [60, "#9A9A94"],
    [100, "#3A3A38"],
  ],
};

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lerpColor(a: string, b: string, f: number): string {
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  const ch = (x: number, y: number) =>
    Math.round(x + (y - x) * f)
      .toString(16)
      .padStart(2, "0");
  return `#${ch(ar, br)}${ch(ag, bg)}${ch(ab, bb)}`;
}

// Smooth ramp whose position is a logarithmic function of how close the
// score is to 100, so the top of the scale gets most of the color range.
// Hurricane scores are percentile ranks over a country that is mostly
// zero-exposure, so nearly every coastal ZCTA lands in the 80s-90s; on a
// linear ramp they all look alike. With c=3: t(80)=0.42, t(90)=0.59,
// t(95)=0.72, t(98)=0.86, t(100)=1. The score itself is unchanged -- this
// only changes how it is drawn. Emitted as one stop per score point (plus
// 99.5) so the piecewise-linear interpolation reads as continuous.
const LOG_C = 3;
const LOG_COLORS: [number, string][] = [
  [0, "#f5f5f5"],
  [0.3, "#9ad3d1"],
  [0.55, "#2a9a9f"],
  [0.75, "#00707A"],
  [0.9, "#07454f"],
  [1, "#0b1d3a"],
];

function logRampStops(): ColorStop[] {
  const norm = Math.log((100 + LOG_C) / LOG_C);
  const scores = [...Array.from({ length: 100 }, (_, i) => i), 99.5, 100].sort((a, b) => a - b);
  return scores.map((s): ColorStop => {
    const t = Math.log((100 + LOG_C) / (100 - s + LOG_C)) / norm;
    let i = 0;
    while (i < LOG_COLORS.length - 2 && t > LOG_COLORS[i + 1][0]) i++;
    const [t0, c0] = LOG_COLORS[i];
    const [t1, c1] = LOG_COLORS[i + 1];
    return [s, lerpColor(c0, c1, (t - t0) / (t1 - t0))];
  });
}

const LOG_STOPS = logRampStops();

export function colorStopsFor(layer: LayerMeta): ColorStop[] {
  if (layer.category === "hurricane") return LOG_STOPS;
  if (layer.color_ramp) {
    return [
      [0, layer.color_ramp[0]],
      [50, layer.color_ramp[1]],
      [100, layer.color_ramp[2]],
    ];
  }
  return (
    CATEGORY_COLOR_STOPS[layer.category] ?? [
      [0, "#f5f5f5"],
      [100, layer.color ?? "#7B2D8E"],
    ]
  );
}
