import { Component, createSignal, onMount, For, Show } from "solid-js";
import type { LeaderboardEntry } from "../types";
import { api } from "../services/api";
import { authStore } from "../stores/authStore";

const Leaderboard: Component = () => {
  const [entries, setEntries] = createSignal<LeaderboardEntry[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [hasMore, setHasMore] = createSignal(false);

  async function loadEntries(offset = 0) {
    try {
      const data = await api.getLeaderboard(offset);
      if (offset === 0) {
        setEntries(data.entries);
      } else {
        setEntries((prev) => [...prev, ...data.entries]);
      }
      setHasMore(data.hasMore);
    } catch (e) {
      console.error("Failed to load leaderboard:", e);
    } finally {
      setLoading(false);
    }
  }

  onMount(() => loadEntries());

  function loadMore() {
    loadEntries(entries().length);
  }

  function winRate(e: LeaderboardEntry): string {
    if (e.totalMatches === 0) return "0%";
    return Math.round((e.totalWins / e.totalMatches) * 100) + "%";
  }

  return (
    <div class="flex-1 flex flex-col items-center p-6 max-w-2xl mx-auto w-full">
      <h2 class="text-2xl font-bold mb-6">Leaderboard</h2>

      <Show when={loading()}>
        <div class="animate-pulse text-gray-400">Loading...</div>
      </Show>

      <Show when={!loading() && entries().length === 0}>
        <p class="text-gray-500">No ranked players yet. Play a match to get on the board!</p>
      </Show>

      <Show when={!loading() && entries().length > 0}>
        {}
        <div class="w-full grid grid-cols-[3rem_1fr_5rem_5rem_4rem] gap-2 px-4 py-2 text-xs text-gray-500 uppercase tracking-wider">
          <div>#</div>
          <div>Player</div>
          <div class="text-right">ELO</div>
          <div class="text-right">W / L</div>
          <div class="text-right">Win%</div>
        </div>

        <div class="w-full space-y-1">
          <For each={entries()}>
            {(entry) => {
              const isMe = () => entry.userId === authStore.user()?.id;
              return (
                <div
                  class={`grid grid-cols-[3rem_1fr_5rem_5rem_4rem] gap-2 items-center px-4 py-3 rounded-lg border ${
                    isMe() ? "bg-brand/10 border-brand/30" : "bg-gray-900 border-gray-800"
                  }`}
                >
                  {}
                  <div class="text-gray-500 font-mono text-sm">
                    {entry.rank <= 3 ? (
                      <span
                        class={
                          entry.rank === 1
                            ? "text-yellow-400"
                            : entry.rank === 2
                              ? "text-gray-300"
                              : "text-amber-600"
                        }
                      >
                        {entry.rank === 1 ? "🥇" : entry.rank === 2 ? "🥈" : "🥉"}
                      </span>
                    ) : (
                      entry.rank
                    )}
                  </div>

                  {}
                  <div class="truncate">
                    <span class={`font-semibold ${isMe() ? "text-brand" : ""}`}>
                      {entry.username}
                    </span>
                    <Show when={isMe()}>
                      <span class="text-xs text-brand ml-1">(you)</span>
                    </Show>
                  </div>

                  {}
                  <div class="text-right font-mono text-sm font-bold text-brand tabular-nums">
                    {entry.rngScore}
                  </div>

                  {}
                  <div class="text-right text-sm tabular-nums">
                    <span class="text-green-400">{entry.totalWins}</span>
                    <span class="text-gray-600"> / </span>
                    <span class="text-red-400">{entry.totalLosses}</span>
                  </div>

                  {}
                  <div class="text-right text-sm text-gray-400 tabular-nums">{winRate(entry)}</div>
                </div>
              );
            }}
          </For>
        </div>

        <Show when={hasMore()}>
          <button
            onClick={loadMore}
            class="mt-4 px-6 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-600 rounded-lg transition-colors"
          >
            Load More
          </button>
        </Show>
      </Show>
    </div>
  );
};

export default Leaderboard;
