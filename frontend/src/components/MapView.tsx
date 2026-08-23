import maplibregl, { Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import type { LayerMeta } from "../api";
import { layerGeoJsonUrl } from "../api";
import basemapStyle from "../basemapStyle.json";
import { colorStopsFor } from "../colorRamps";

// This dashboard is CONUS-only: CONUS spans roughly -125..-66 lon,
// 24..50 lat (config.CONUS_BBOX in the pipeline); padded ~300mi (~5deg)
// past each edge so there's a bit of pan room without ever showing the
// rest of the globe. The initial view is fit to this exact box at load
// time (not a hardcoded center/zoom guess), so it's centered on CONUS and
// its aspect ratio naturally follows CONUS's own shape regardless of the
// viewport's aspect ratio.
const MAX_BOUNDS: maplibregl.LngLatBoundsLike = [
  [-130, 19],
  [-61, 55],
];

const CATEGORY_SOURCE = "active-category";
const CATEGORY_FILL_LAYER = "active-category-fill";
const CATEGORY_LINE_LAYER = "active-category-line";
const HIGHLIGHT_SOURCE = "zip-highlight";
const HIGHLIGHT_LINE_LAYER = "zip-highlight-line";

// No API key needed: vector tiles from OpenFreeMap (free, unlimited, no
// registration -- https://openfreemap.org), trimmed from their "liberty"
// style down to ~19 layers (regenerate via
// pixi run python scripts/build_basemap_style.py) so the map stays minimal
// but keeps interstate highways and park/forest/water/urban landuse
// symbology per the project brief.
const STYLE = basemapStyle as maplibregl.StyleSpecification;

function fillColorExpression(
  layer: LayerMeta,
): maplibregl.ExpressionSpecification {
  const stops = colorStopsFor(layer);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const expr: any[] = ["interpolate", ["linear"], ["get", "score"]];
  for (const [stop, color] of stops) {
    expr.push(stop, color);
  }
  return expr as maplibregl.ExpressionSpecification;
}

export interface Highlight {
  feature: GeoJSON.Feature | null;
  /** Zoom/pan to fit the feature -- true for a zip search result, false
   * for a map click (the user is already looking at it). */
  fitBounds: boolean;
}

export interface MapViewProps {
  activeLayer: LayerMeta | null;
  highlight: Highlight;
  layerStatus: (loading: boolean, error: string | null) => void;
  onPolygonClick: (zcta5: string) => void;
}

export default function MapView({
  activeLayer,
  highlight,
  layerStatus,
  onPolygonClick,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const loadedRef = useRef(false);
  const onPolygonClickRef = useRef(onPolygonClick);
  onPolygonClickRef.current = onPolygonClick;

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE,
      bounds: MAX_BOUNDS,
      minZoom: 2,
      maxZoom: 12,
      renderWorldCopies: false,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("click", CATEGORY_FILL_LAYER, (e) => {
      const zcta5 = e.features?.[0]?.properties?.zcta5;
      if (zcta5) onPolygonClickRef.current(String(zcta5));
    });
    map.on("mouseenter", CATEGORY_FILL_LAYER, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", CATEGORY_FILL_LAYER, () => {
      map.getCanvas().style.cursor = "";
    });
    map.on("load", () => {
      loadedRef.current = true;
      // Constrain panning/zooming out to the same box the initial view
      // was fit to, so CONUS plus its padding is the whole world this map
      // ever shows.
      map.setMaxBounds(MAX_BOUNDS);

      map.addSource(HIGHLIGHT_SOURCE, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: HIGHLIGHT_LINE_LAYER,
        type: "line",
        source: HIGHLIGHT_SOURCE,
        paint: { "line-color": "#ffffff", "line-width": 3 },
      });
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      loadedRef.current = false;
    };
  }, []);

  const sourceListenerRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !activeLayer) return;

    const applyLayer = () => {
      if (sourceListenerRef.current) {
        map.off("sourcedata", sourceListenerRef.current);
        sourceListenerRef.current = null;
      }
      if (map.getLayer(CATEGORY_FILL_LAYER)) map.removeLayer(CATEGORY_FILL_LAYER);
      if (map.getLayer(CATEGORY_LINE_LAYER)) map.removeLayer(CATEGORY_LINE_LAYER);
      if (map.getSource(CATEGORY_SOURCE)) map.removeSource(CATEGORY_SOURCE);

      layerStatus(true, null);
      map.addSource(CATEGORY_SOURCE, {
        type: "geojson",
        data: layerGeoJsonUrl(activeLayer.category),
      });
      map.addLayer(
        {
          id: CATEGORY_FILL_LAYER,
          type: "fill",
          source: CATEGORY_SOURCE,
          paint: { "fill-color": fillColorExpression(activeLayer), "fill-opacity": 0.75 },
        },
        HIGHLIGHT_LINE_LAYER,
      );
      map.addLayer(
        {
          id: CATEGORY_LINE_LAYER,
          type: "line",
          source: CATEGORY_SOURCE,
          paint: { "line-color": "#00000022", "line-width": 0.3 },
        },
        HIGHLIGHT_LINE_LAYER,
      );

      const checkLoaded = () => {
        if (!map.getSource(CATEGORY_SOURCE)) return;
        if (map.isSourceLoaded(CATEGORY_SOURCE)) {
          layerStatus(false, null);
          map.off("sourcedata", checkLoaded);
          sourceListenerRef.current = null;
        }
      };
      sourceListenerRef.current = checkLoaded;
      map.on("sourcedata", checkLoaded);

      // The layer endpoint 404s until that category has been generated by
      // the pipeline (only Severe Convective + Winter Weather exist so far
      // in this prototype phase).
      fetch(layerGeoJsonUrl(activeLayer.category)).then((res) => {
        if (!res.ok) {
          layerStatus(false, `"${activeLayer.name}" hasn't been generated by the pipeline yet.`);
        }
      });
    };

    if (loadedRef.current) applyLayer();
    else map.once("load", applyLayer);
  }, [activeLayer, layerStatus]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) return;
    const source = map.getSource(HIGHLIGHT_SOURCE) as maplibregl.GeoJSONSource | undefined;
    if (!source) return;

    const { feature, fitBounds } = highlight;
    if (!feature) {
      source.setData({ type: "FeatureCollection", features: [] });
      return;
    }
    source.setData({ type: "FeatureCollection", features: [feature] });
    if (!fitBounds) return;

    const bounds = new maplibregl.LngLatBounds();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const extend = (coords: any) => {
      if (typeof coords[0] === "number") {
        bounds.extend(coords as [number, number]);
      } else {
        (coords as unknown[]).forEach(extend);
      }
    };
    extend((feature.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon).coordinates);
    map.fitBounds(bounds, { padding: 80, maxZoom: 10, duration: 800 });
  }, [highlight]);

  return <div ref={containerRef} className="h-full w-full" />;
}
