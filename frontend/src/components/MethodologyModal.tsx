interface Row {
  name: string;
  source: string;
  method: string;
}

const ROWS: Row[] = [
  {
    name: "Severe Convective",
    source: "NCEI Storm Events (tornado, hail, thunderstorm wind), 2015-2024",
    method:
      "Counts storm reports within 15 miles of each ZCTA's center, weighted by severity. We then adjust for population density, because more people means more reports, not necessarily more storms.",
  },
  {
    name: "Winter Weather",
    source: "gridMET daily precipitation and max temperature, 2015-2024",
    method:
      "The average number of days per year with at least 0.01 inches of precipitation and a high at or below 32F. It comes from physical measurements rather than human reports, so reporting habits don't skew it.",
  },
  {
    name: "Flood",
    source: "FEMA National Flood Hazard Layer",
    method: "The share of each ZCTA's area inside a Special Flood Hazard Area (Zone A, AE, V or VE).",
  },
  {
    name: "Wildfire",
    source: "USFS Wildfire Hazard Potential (2020) + MTBS burn perimeters, 2015-2024",
    method:
      "70% average Wildfire Hazard Potential across the ZCTA, plus 30% the number of past burns that touched it.",
  },
  {
    name: "Hurricane / Tropical",
    source: "STORM synthetic tropical cyclone dataset (present-day climate)",
    method:
      "The average maximum wind speed you'd expect once every 50 years, taken from 10,000 years of simulated storms. It measures wind alone, with no building values or loss estimates mixed in.",
  },
  {
    name: "Drought",
    source: "U.S. Drought Monitor county statistics, 2015-2024",
    method:
      "The average share of time spent in moderate-or-worse drought (D0 and above), spread from counties onto ZCTAs by area.",
  },
  {
    name: "Extreme Heat",
    source: "gridMET daily max temperature and minimum relative humidity, 2015-2024",
    method:
      "A blend: 60% average days per year above 90F and 40% average days per year with a heat index above 100F.",
  },
  {
    name: "Seismic",
    source: "USGS National Seismic Hazard Model (2018) + Volcanic Threat Assessment",
    method:
      "80% expected peak ground shaking (2% chance of being exceeded in 50 years) and 20% how close the ZCTA is to a volcanic center.",
  },
  {
    name: "Air Quality",
    source: "CDC/EPA fused daily census-tract PM2.5, 2016-2020",
    method:
      "The average number of days per year when PM2.5 tops 35.4 ug/m3, the point where the AQI reaches \"Unhealthy for Sensitive Groups.\" The data blends monitors with models, so rural areas without monitors are still covered. It runs 2016-2020 because CDC's tract-level data doesn't go further.",
  },
  {
    name: "Composite",
    source: "Derived",
    method:
      "A weighted power mean (exponent 3) of the nine category scores. Unlike a plain average, it lets places with several serious hazards score higher. Drought, Seismic and Air Quality count for 5% each, and the other six for 15% each.",
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
          Created by Max Keller
          <br />
          <a
            href="https://www.linkedin.com/in/max-keller-46343a384"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline"
          >
            www.linkedin.com/in/max-keller-46343a384
          </a>
        </p>

        <p className="mb-4 text-sm text-gray-600">
          These scores reflect historical hazard patterns, not real-time or
          forecasted conditions. Each one is a 0-100 percentile rank of a raw metric,
          calculated ahead of time from recent history (2015-2024 unless noted), so
          nothing here updates with current weather. Ranking by percentile lets
          categories with different units sit on the same scale. Wildfire, seismic and
          hurricane come from models of long-term hazard rather than past events.
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
          Zip codes are matched to ZCTAs using the HRSA crosswalk. A PO-box-only zip
          has no land area of its own, so it shows the ZCTA that contains it, and the
          detail panel lists both codes when they differ.
        </p>
      </div>
    </div>
  );
}
