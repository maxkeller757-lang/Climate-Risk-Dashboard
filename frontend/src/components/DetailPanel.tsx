import type { ZipDetail } from "../api";

export interface DetailPanelProps {
  detail: ZipDetail | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onClose: () => void;
}

function scoreColor(score: number): string {
  if (score >= 66) return "#C62828";
  if (score >= 33) return "#F9A825";
  return "#2E7D32";
}

// bottom-16 rather than bottom-6: the map's OpenStreetMap/MapLibre
// attribution control sits fixed to the true bottom-right corner, and at
// bottom-6 this panel's lower edge ran underneath it by ~20px. The offset
// only needs to clear that corner once -- the panel is bottom-anchored, so
// its lower edge stays put regardless of how tall the content above it is.
const POSITION = "absolute bottom-16 right-4 z-10";

export default function DetailPanel({
  detail,
  collapsed,
  onToggleCollapsed,
  onClose,
}: DetailPanelProps) {
  if (!detail) return null;

  const label = detail.zip ? `Zip ${detail.zip}` : `ZCTA ${detail.zcta}`;

  if (collapsed) {
    return (
      <button
        onClick={onToggleCollapsed}
        title="Show zip detail"
        className={`${POSITION} flex items-center gap-2 rounded-lg bg-white/95 px-3 py-2 text-sm font-medium text-gray-700 shadow-lg backdrop-blur hover:bg-gray-50`}
      >
        <span
          className="h-3 w-3 shrink-0 rounded-full"
          style={{
            background:
              detail.composite_score !== null ? scoreColor(detail.composite_score) : "#9ca3af",
          }}
        />
        {label}
        <span aria-hidden>▸</span>
      </button>
    );
  }

  return (
    <div className={`${POSITION} w-96 rounded-lg bg-white/95 p-4 shadow-lg backdrop-blur`}>
      <div className="mb-2 flex items-start justify-between">
        <div>
          {detail.zip ? (
            <>
              <div className="text-xs text-gray-500">Zip {detail.zip}</div>
              <div className="text-xs text-gray-400">ZCTA {detail.zcta}</div>
            </>
          ) : (
            <div className="text-xs text-gray-500">ZCTA {detail.zcta}</div>
          )}
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

      <div className="mb-3 flex items-baseline gap-2">
        <span className="text-3xl font-bold" style={{
          color: detail.composite_score !== null ? scoreColor(detail.composite_score) : "#9ca3af",
        }}>
          {detail.composite_score ?? "—"}
        </span>
        <span className="text-sm text-gray-500">composite risk score</span>
      </div>
      {detail.composite_score === null && (
        <p className="mb-3 text-xs text-amber-600">
          Composite not yet computed (Phase 4 hasn't run in this prototype).
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        {detail.categories.map((cat) => (
          <div key={cat.category} className="flex items-center gap-2">
            <span className="w-28 shrink-0 text-xs text-gray-600">{cat.name}</span>
            <div className="h-2 flex-1 rounded bg-gray-100">
              <div
                className="h-2 rounded"
                style={{ width: `${cat.score}%`, background: cat.color }}
              />
            </div>
            <span className="w-8 text-right text-xs font-medium text-gray-700">
              {cat.score.toFixed(0)}
            </span>
          </div>
        ))}
        {detail.categories.length === 0 && (
          <p className="text-xs text-gray-400">No category scores available yet.</p>
        )}
      </div>
    </div>
  );
}
