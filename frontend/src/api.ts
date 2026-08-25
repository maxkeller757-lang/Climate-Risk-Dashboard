export interface LayerMeta {
  category: string;
  name: string;
  description: string;
  color?: string;
  color_ramp?: string[];
}

export interface CategoryScore {
  name: string;
  category: string;
  score: number;
  raw_metric: number | null;
  color: string;
}

export interface ZipDetail {
  zip: string | null;
  zcta: string;
  composite_score: number | null;
  categories: CategoryScore[];
}

const BASE = "/api";

export async function fetchLayers(): Promise<LayerMeta[]> {
  const res = await fetch(`${BASE}/layers`);
  if (!res.ok) throw new Error("Failed to load layers");
  return res.json();
}

export function layerGeoJsonUrl(category: string): string {
  return `${BASE}/layer/${category}`;
}

export async function fetchZipExists(zip: string): Promise<boolean> {
  const res = await fetch(`${BASE}/zip/${zip}/exists`);
  if (!res.ok) return false;
  const data = await res.json();
  return Boolean(data.exists);
}

export async function fetchZipDetail(zip: string): Promise<ZipDetail> {
  const res = await fetch(`${BASE}/zip/${zip}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Zip ${zip} not found`);
  }
  return res.json();
}

export interface TopZone {
  zcta: string;
  state: string | null;
  score: number;
}

export interface LayerTopZones {
  category: string;
  name: string;
  zones: TopZone[];
}

export async function fetchLayerTopZones(
  category: string,
): Promise<LayerTopZones> {
  const res = await fetch(`${BASE}/layer/${category}/top`);
  if (!res.ok) throw new Error(`No top zones for ${category}`);
  return res.json();
}

export async function fetchZctaDetail(zcta: string): Promise<ZipDetail> {
  const res = await fetch(`${BASE}/zcta/${zcta}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `ZCTA ${zcta} not found`);
  }
  return res.json();
}

export async function fetchZctaGeometry(
  zcta: string,
): Promise<GeoJSON.Feature> {
  const res = await fetch(`${BASE}/zcta/${zcta}/geometry`);
  if (!res.ok) throw new Error(`No geometry for ZCTA ${zcta}`);
  return res.json();
}
