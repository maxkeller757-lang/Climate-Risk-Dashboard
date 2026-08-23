import { FormEvent, useState } from "react";

export interface ZipSearchProps {
  onSearch: (zip: string) => void;
  loading: boolean;
  error: string | null;
}

export default function ZipSearch({ onSearch, loading, error }: ZipSearchProps) {
  const [value, setValue] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (/^\d{5}$/.test(value)) onSearch(value);
  }

  return (
    <div className="absolute right-4 top-4 z-10 w-64 rounded-lg bg-white/95 p-3 shadow-lg backdrop-blur">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value.replace(/\D/g, "").slice(0, 5))}
          placeholder="Enter zip code"
          inputMode="numeric"
          className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
        />
        <button
          type="submit"
          disabled={loading || value.length !== 5}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-40"
        >
          {loading ? "..." : "Go"}
        </button>
      </form>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}
