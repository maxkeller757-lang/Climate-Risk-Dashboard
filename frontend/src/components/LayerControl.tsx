import { useState } from "react";
import type { LayerMeta } from "../api";

export interface LayerControlProps {
  layers: LayerMeta[];
  activeCategory: string | null;
  onSelect: (category: string) => void;
}

export default function LayerControl({
  layers,
  activeCategory,
  onSelect,
}: LayerControlProps) {
  const [collapsed, setCollapsed] = useState(false);
  const activeLayer = layers.find((l) => l.category === activeCategory) ?? null;

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        title="Show hazard layer options"
        className="absolute left-4 top-4 z-10 flex items-center gap-2 rounded-lg bg-white/95 px-3 py-2 text-sm font-medium text-gray-700 shadow-lg backdrop-blur hover:bg-gray-50"
      >
        <span
          className="h-3 w-3 shrink-0 rounded-full"
          style={{
            background: activeLayer?.color_ramp
              ? `linear-gradient(90deg, ${activeLayer.color_ramp.join(",")})`
              : activeLayer?.color,
          }}
        />
        {activeLayer?.name ?? "Hazard Layer"}
        <span aria-hidden>▸</span>
      </button>
    );
  }

  return (
    <div className="absolute left-4 top-4 z-10 w-64 rounded-lg bg-white/95 p-3 shadow-lg backdrop-blur">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700">Hazard Layer</h2>
        <button
          onClick={() => setCollapsed(true)}
          title="Collapse (uncovers the NW corner of the map)"
          className="rounded px-1 text-gray-400 hover:text-gray-700"
        >
          ◂
        </button>
      </div>
      <div className="flex flex-col gap-1">
        {layers.map((layer) => (
          <button
            key={layer.category}
            onClick={() => onSelect(layer.category)}
            className={`flex items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition ${
              activeCategory === layer.category
                ? "bg-gray-900 text-white"
                : "text-gray-700 hover:bg-gray-100"
            }`}
          >
            <span
              className="h-3 w-3 shrink-0 rounded-full"
              style={{
                background: layer.color_ramp
                  ? `linear-gradient(90deg, ${layer.color_ramp.join(",")})`
                  : layer.color,
              }}
            />
            {layer.name}
          </button>
        ))}
      </div>
    </div>
  );
}
