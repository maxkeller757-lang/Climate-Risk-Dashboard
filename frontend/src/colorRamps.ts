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
};

export function colorStopsFor(layer: LayerMeta): ColorStop[] {
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
