import { useCallback, useEffect, useState } from "react";
import {
  fetchLayerTopZones,
  fetchLayers,
  fetchZctaDetail,
  fetchZctaGeometry,
  fetchZipDetail,
  LayerMeta,
  LayerTopZones,
  ZipDetail,
} from "./api";
import DetailPanel from "./components/DetailPanel";
import Legend from "./components/Legend";
import LayerControl from "./components/LayerControl";
import MapView, { Highlight } from "./components/MapView";
import MethodologyModal from "./components/MethodologyModal";
import TopZonesPanel from "./components/TopZonesPanel";
import ZipSearch from "./components/ZipSearch";

const NO_HIGHLIGHT: Highlight = { feature: null, fitBounds: false };

/**
 * Which of the two bottom-right panels to show. They share a slot, and the
 * one displayed is whichever the user acted on most recently: selecting a
 * polygon (click or zip search) shows that polygon's breakdown, selecting a
 * layer shows where that hazard is worst nationally.
 */
type Focus = "polygon" | "layer";

export default function App() {
  const [layers, setLayers] = useState<LayerMeta[]>([]);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [layerLoading, setLayerLoading] = useState(false);
  const [layerError, setLayerError] = useState<string | null>(null);
  const [showMethodology, setShowMethodology] = useState(false);

  const [zipDetail, setZipDetail] = useState<ZipDetail | null>(null);
  const [highlight, setHighlight] = useState<Highlight>(NO_HIGHLIGHT);
  const [zipLoading, setZipLoading] = useState(false);
  const [zipError, setZipError] = useState<string | null>(null);

  const [focus, setFocus] = useState<Focus>("layer");
  const [topZones, setTopZones] = useState<LayerTopZones | null>(null);
  const [topLoading, setTopLoading] = useState(false);
  const [topError, setTopError] = useState<string | null>(null);

  useEffect(() => {
    fetchLayers().then((data) => {
      setLayers(data);
      setActiveCategory(data[0]?.category ?? null);
    });
  }, []);

  const layerStatus = useCallback((loading: boolean, error: string | null) => {
    setLayerLoading(loading);
    setLayerError(error);
  }, []);

  // Selecting a layer is the other half of the focus rule: fetch where
  // that hazard is worst, and hand the panel slot back to the layer view.
  useEffect(() => {
    if (!activeCategory) return;
    let cancelled = false;
    setFocus("layer");
    setTopLoading(true);
    setTopError(null);
    fetchLayerTopZones(activeCategory)
      .then((data) => {
        if (!cancelled) setTopZones(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setTopZones(null);
          setTopError(err instanceof Error ? err.message : "Could not load top zones");
        }
      })
      .finally(() => {
        if (!cancelled) setTopLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeCategory]);

  async function showZcta(zcta: string, fitBounds: boolean) {
    setFocus("polygon");
    setZipLoading(true);
    setZipError(null);
    try {
      const [detail, geometry] = await Promise.all([
        fetchZctaDetail(zcta),
        fetchZctaGeometry(zcta),
      ]);
      setZipDetail(detail);
      setHighlight({ feature: geometry, fitBounds });
    } catch (err) {
      setZipError(err instanceof Error ? err.message : `ZCTA ${zcta} not found`);
      setZipDetail(null);
      setHighlight(NO_HIGHLIGHT);
    } finally {
      setZipLoading(false);
    }
  }

  async function handleZipSearch(zip: string) {
    setFocus("polygon");
    setZipLoading(true);
    setZipError(null);
    try {
      const detail = await fetchZipDetail(zip);
      setZipDetail(detail);
      const geometry = await fetchZctaGeometry(detail.zcta);
      setHighlight({ feature: geometry, fitBounds: true });
    } catch (err) {
      setZipError(err instanceof Error ? err.message : "Zip not found");
      setZipDetail(null);
      setHighlight(NO_HIGHLIGHT);
    } finally {
      setZipLoading(false);
    }
  }

  const handlePolygonClick = useCallback((zcta5: string) => {
    showZcta(zcta5, false);
  }, []);

  const activeLayer = layers.find((l) => l.category === activeCategory) ?? null;

  return (
    <div className="relative h-screen w-screen">
      <MapView
        activeLayer={activeLayer}
        highlight={highlight}
        layerStatus={layerStatus}
        onPolygonClick={handlePolygonClick}
      />
      <LayerControl
        layers={layers}
        activeCategory={activeCategory}
        onSelect={setActiveCategory}
      />
      <ZipSearch onSearch={handleZipSearch} loading={zipLoading} error={zipError} />
      <Legend layer={activeLayer} />
      {/* One slot, two panels: whichever the user acted on most recently. */}
      {focus === "polygon" ? (
        <DetailPanel
          detail={zipDetail}
          onClose={() => {
            setZipDetail(null);
            setHighlight(NO_HIGHLIGHT);
            // Fall back to the layer view rather than leaving the slot
            // empty -- there is always an active layer to describe.
            setFocus("layer");
          }}
        />
      ) : (
        <TopZonesPanel
          data={topZones}
          loading={topLoading}
          error={topError}
          onSelectZcta={(zcta) => showZcta(zcta, true)}
          onClose={() => setTopZones(null)}
        />
      )}
      {layerLoading && (
        <div className="absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded bg-white/95 px-3 py-1 text-xs text-gray-600 shadow">
          Loading layer…
        </div>
      )}
      {layerError && (
        <div className="absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded bg-amber-50 px-3 py-1 text-xs text-amber-700 shadow">
          {layerError}
        </div>
      )}
      <button
        onClick={() => setShowMethodology(true)}
        className="absolute bottom-6 left-1/2 z-10 -translate-x-1/2 rounded-lg bg-white/95 px-3 py-1.5 text-xs font-medium text-gray-600 shadow-lg backdrop-blur hover:text-gray-900"
      >
        Methodology
      </button>
      {showMethodology && (
        <MethodologyModal onClose={() => setShowMethodology(false)} />
      )}
    </div>
  );
}
