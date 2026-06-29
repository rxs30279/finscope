"use client";

import { useRouter } from "next/navigation";
import { useWatchlist } from "@/app/providers";
import { companyHref } from "@/lib/company";
import WatchlistTab from "@/components/WatchlistTab";

export default function WatchlistPageClient() {
  const router = useRouter();
  const {
    watchlists,
    createWatchlist,
    renameWatchlist,
    deleteWatchlist,
    addToWatchlist,
    removeFromWatchlist,
  } = useWatchlist();

  return (
    <WatchlistTab
      watchlists={watchlists}
      onSelect={(sym: string) => router.push(companyHref(sym))}
      onCreateList={createWatchlist}
      onRenameList={renameWatchlist}
      onDeleteList={deleteWatchlist}
      onAddSymbol={addToWatchlist}
      onRemoveSymbol={removeFromWatchlist}
    />
  );
}
