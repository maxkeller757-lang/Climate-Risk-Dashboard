/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL layer GeoJSON files are fetched from. Unset in local dev
   * (falls back to the /layers static path); set to the Cloudflare R2
   * bucket URL for a deployed build. See src/api.ts::layerGeoJsonUrl. */
  readonly VITE_LAYERS_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
