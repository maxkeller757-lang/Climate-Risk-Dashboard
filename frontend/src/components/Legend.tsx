import type { LayerMeta } from "../api";
import { colorStopsFor } from "../colorRamps";

export default function Legend({ layer }: { layer: LayerMeta | null }) {
  if (!layer) return null;
  const stops = colorStopsFor(layer);
  const gradient = `linear-gradient(90deg, ${stops
    .map(([pct, color]) => `${color} ${pct}%`)
    .join(", ")})`;

  return (
    <div className="absolute bottom-6 left-4 z-10 rounded-lg bg-white/95 p-3 shadow-lg backdrop-blur">
      <div className="mb-1 text-xs font-semibold text-gray-700">{layer.name} risk score</div>
      <div className="h-2 w-48 rounded" style={{ background: gradient }} />
      <div className="mt-1 flex justify-between text-[10px] text-gray-500">
        <span>0 (low)</span>
        <span>100 (high)</span>
      </div>
    </div>
  );
}
