import type { LayerTopZones } from "../api";

export interface TopZonesPanelProps {
  data: LayerTopZones | null;
  loading: boolean;
  error: string | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSelectZcta: (zcta: string) => void;
  onClose: () => void;
}

// bottom-16 rather than bottom-6: the map's OpenStreetMap/MapLibre
// attribution control sits fixed to the true bottom-right corner, and at
// bottom-6 this panel's lower edge ran underneath it by ~20px. The offset
// only needs to clear that corner once -- the panel is bottom-anchored, so
// its lower edge stays put regardless of how tall the content above it is.
const POSITION = "absolute bottom-16 right-4 z-10";

/**
 * Highest-risk zones for the active layer.
 *
 * Takes the same slot as the single-polygon breakdown, and which one shows
 * is decided by whichever the user touched most recently. Picking a layer
 * asks "where is this hazard worst?", and a breakdown of whatever polygon
 * happened to be selected earlier cannot answer that.
 */
export default function TopZonesPanel({
  data,
  loading,
  error,
  collapsed,
  onToggleCollapsed,
  onSelectZcta,
  onClose,
}: TopZonesPanelProps) {
  if (!data && !loading && !error) return null;

  if (collapsed) {
    return (
      <button
        onClick={onToggleCollapsed}
        title="Show highest-risk zones"
        className={`${POSITION} flex items-center gap-2 rounded-lg bg-white/95 px-3 py-2 text-sm font-medium text-gray-700 shadow-lg backdrop-blur hover:bg-gray-50`}
      >
        Highest risk{data ? `: ${data.name}` : ""}
        <span aria-hidden>▸</span>
      </button>
    );
  }

  return (
    <div className={`${POSITION} w-96 rounded-lg bg-white/95 p-4 shadow-lg backdrop-blur`}>
      <div className="mb-2 flex items-start justify-between">
        <div>
          <div className="text-xs font-semibold text-gray-700">
            Highest risk{data ? `: ${data.name}` : ""}
          </div>
          <div className="text-[11px] text-gray-400">
            Ranked across all US zip codes
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onToggleCollapsed}
            title="Collapse"
            className="rounded px-1 text-gray-400 hover:text-gray-700"
          >
            ▾
          </button>
          <button onClick={onClose} className="text-sm text-gray-400 hover:text-gray-700">
            ✕
          </button>
        </div>
      </div>

      {loading && <p className="text-xs text-gray-500">Loading…</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}

      {data && !loading && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-400">
              <th className="w-6 pb-1 text-left font-medium">#</th>
              <th className="pb-1 text-left font-medium">Zip</th>
              <th className="pb-1 text-left font-medium">Location</th>
              <th className="pb-1 text-right font-medium">Score</th>
            </tr>
          </thead>
          <tbody>
            {data.zones.map((z, i) => {
              const location = [z.county, z.state].filter(Boolean).join(", ");
              return (
                <tr key={z.zcta} className="border-t border-gray-100">
                  <td className="py-1.5 text-gray-400">{i + 1}</td>
                  <td className="py-1.5">
                    <button
                      onClick={() => onSelectZcta(z.zcta)}
                      className="font-medium text-gray-800 underline decoration-gray-300 underline-offset-2 hover:decoration-gray-700"
                      title="Show this zip's full breakdown"
                    >
                      {z.zcta}
                    </button>
                  </td>
                  <td
                    className="py-1.5 text-gray-600"
                    title={
                      z.population > 0
                        ? `~${z.population.toLocaleString()} people (est.)`
                        : undefined
                    }
                  >
                    {location || "—"}
                  </td>
                  <td className="py-1.5 text-right font-medium text-gray-800">
                    {z.score.toFixed(5)}
                  </td>
                </tr>
              );
            })}
            {data.zones.length === 0 && (
              <tr>
                <td colSpan={4} className="py-2 text-gray-400">
                  No scored zones for this layer.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
