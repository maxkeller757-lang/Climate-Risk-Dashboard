interface Row {
  name: string;
  source: string;
  method: string;
}

const ROWS: Row[] = [
  {
    name: "Severe Convective",
    source: "NCEI Storm Events (Tornado/Hail/Thunderstorm Wind), 2015-2024",
    method:
      "15mi buffer around ZCTA centroid, severity-weighted event count, then detrended against Census population density to correct for the fact that report density tracks population as much as it tracks real storm activity.",
  },
  {
    name: "Winter Weather",
    source: "NCEI Storm Events (Winter/Ice Storm, Heavy Snow, Blizzard), 2015-2024",
    method:
      "These event types are recorded by NWS forecast zone, not point location -- % area overlay against real NWS zone polygons, severity-weighted.",
  },
  {
    name: "Flood",
    source: "FEMA National Flood Hazard Layer (live ArcGIS service)",
    method: "% of ZCTA area inside a Special Flood Hazard Area (Zone A/AE/V/VE).",
  },
  {
    name: "Wildfire",
    source: "USFS Wildfire Hazard Potential (2020) + MTBS burn perimeters, 2015-2024",
    method:
      "70% zonal-mean Wildfire Hazard Potential (point-in-time model) + 30% count of historical burns intersecting the ZCTA.",
  },
  {
    name: "Hurricane / Tropical",
    source: "NOAA NHC HURDAT2 best-track database, 2015-2024",
    method: "Wind-speed-squared-weighted exposure from track point proximity, 150mi linear decay.",
  },
  {
    name: "Drought",
    source: "U.S. Drought Monitor county statistics, 2015-2024",
    method: "Average % of time in D0-or-worse drought, area-weighted from county to ZCTA.",
  },
  {
    name: "Extreme Heat",
    source: "gridMET daily max temp + min relative humidity, 2015-2024",
    method:
      "Blend of 60% avg days/year >90F and 40% avg days/year with NWS heat index (Rothfusz regression) >100F.",
  },
  {
    name: "Seismic",
    source: "USGS National Seismic Hazard Model (2018) + National Volcanic Threat Assessment",
    method:
      "80% zonal-mean PGA (2% probability of exceedance in 50yr, point-in-time model) + 20% distance-decayed proximity to CONUS volcanic centers.",
  },
  {
    name: "Composite",
    source: "Derived",
    method:
      "Weighted power-mean (exponent 3) of the 8 category percentiles, not a plain average -- categories that are already high contribute disproportionately more, so places with several compounding hazards (e.g. flood + hurricane) score noticeably higher than a plain average would. Drought and Seismic carry a lighter weight (5% each vs. 15%): Drought overlaps heavily with Wildfire/Heat's own signal, and Seismic is a comparatively rare, localized threat nationally. See composite_weights.json.",
  },
];

export default function MethodologyModal({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="absolute inset-0 z-20 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Methodology</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
            ✕
          </button>
        </div>

        <p className="mb-4 text-sm text-gray-600">
          Every score is a 0-100 percentile rank of a raw metric, computed once offline
          by <code className="rounded bg-gray-100 px-1">pipeline/</code> and never
          recomputed at request time -- percentile ranking makes categories with wildly
          different raw units (event counts, % area, days/year) comparable on the same
          scale. Most categories cover 2015-2024; Wildfire Hazard Potential and the
          seismic hazard model are point-in-time model outputs, not event histories, so
          they use the latest published model version instead.
        </p>

        <div className="flex flex-col gap-3">
          {ROWS.map((row) => (
            <div key={row.name} className="border-t border-gray-100 pt-3 first:border-t-0 first:pt-0">
              <div className="text-sm font-semibold text-gray-800">{row.name}</div>
              <div className="text-xs text-gray-500">{row.source}</div>
              <div className="mt-1 text-xs text-gray-600">{row.method}</div>
            </div>
          ))}
        </div>

        <p className="mt-4 text-xs text-gray-400">
          Lightning was considered and dropped for v1 -- no clean, free, consistent
          CONUS-wide feed was found. Zip-to-ZCTA mapping covers direct matches only;
          PO-box-only and split zips aren't resolved yet.
        </p>
      </div>
    </div>
  );
}
