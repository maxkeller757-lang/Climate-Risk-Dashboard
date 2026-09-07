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
    source: "gridMET daily precipitation + max temp, 2015-2024",
    method:
      "Average days per year with at least 0.01in liquid-equivalent precipitation and a max temperature at or below 32F. Previously used NCEI Storm Events (a human-report database), but report density tracked population and each NWS office's own reporting culture as much as real winter weather -- it showed up as scores clustering around Dallas and hard cliffs at state lines. gridMET is model+station-blended physical measurement with no human reporting involved, and a continuous grid has no zone boundary for that kind of artifact to form on.",
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
    method:
      "Wind-speed-squared-weighted exposure from track point proximity, 150mi linear decay. The resulting percentile then gets an S-curve contrast stretch, pushing coastal areas higher and interior areas lower so the layer reflects how sharply hurricane risk falls off inland. That makes this the one score that is not a plain percentile, which is why the composite scales it back down (see Composite).",
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
    name: "Air Quality",
    source: "CDC/EPA fused daily census-tract PM2.5 surface, 2016-2020",
    method:
      "Average days per year with census-tract mean PM2.5 above 35.4 ug/m3 -- the point where the 24-hour AQI passes 100 into 'Unhealthy for Sensitive Groups'. Uses the fused monitor+model surface rather than raw EPA monitor data, because monitors exist in only 31% of CONUS counties and are sited in cities, which would have left most of the map interpolated and biased rural air upward. Apportioned at census-tract granularity (~30x finer than county) to avoid artificial cliffs at county lines; dense-urban PM2.5 elevation is left undamped since it's a real signal, not a reporting artifact. Window is 2016-2020, shorter than other categories, because CDC's tract-level release doesn't extend as far as its county-level one.",
  },
  {
    name: "Composite",
    source: "Derived",
    method:
      "Weighted power-mean (exponent 3) of the 9 category percentiles, not a plain average -- categories that are already high contribute disproportionately more, so places with several compounding hazards (e.g. flood + hurricane) score noticeably higher than a plain average would. Drought, Seismic and Air Quality carry a lighter weight (5% each vs. 15%): Drought overlaps heavily with Wildfire/Heat's own signal, Seismic is a comparatively rare and localized threat nationally, and Air Quality is chronic exposure rather than acute-event risk. Hurricane is additionally scaled by 0.9 here, because its contrast stretch (see above) leaves it on a different scale from the other percentiles and the power-mean would otherwise amplify that a second time -- the layer itself still shows the full stretched score. See composite_weights.json.",
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
          <strong className="text-gray-800">
            These scores reflect historical hazard patterns, not real-time or
            forecasted conditions.
          </strong>{" "}
          Every score is a 0-100 percentile rank of a raw metric, computed once offline
          from recent-years historical data (2015-2024 for most categories, shorter for
          a couple noted below) by{" "}
          <code className="rounded bg-gray-100 px-1">pipeline/</code> and never
          recomputed at request time -- there is no live feed behind this map, and it
          will not reflect a storm, fire, or flood happening today. Percentile ranking
          makes categories with wildly different raw units (event counts, % area,
          days/year) comparable on the same scale. Wildfire Hazard Potential and the
          seismic hazard model are point-in-time model outputs, not event histories, so
          they use the latest published model version instead of a multi-year window.
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
          CONUS-wide feed was found. Zip codes are mapped to ZCTAs via the HRSA
          ZIP-to-ZCTA crosswalk, so PO-box-only zips (which have no land area of
          their own) resolve to the ZCTA containing them -- the detail panel shows
          both codes when they differ.
        </p>
      </div>
    </div>
  );
}
