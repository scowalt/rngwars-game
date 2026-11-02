import { Component, createSignal, onMount, For, Show } from "solid-js";
import { useNavigate } from "@solidjs/router";
import type { MatchResponse } from "../types";
import { api } from "../services/api";

const History: Component = () => {
  const navigate = useNavigate();
  const [matches, setMatches] = createSignal<MatchResponse[]>([]);
  const [loading, setLoading] = createSignal(true);
  const [hasMore, setHasMore] = createSignal(false);

  async function loadMatches(offset = 0) {
    try {
      const data = await api.getMatches(offset);
      if (offset === 0) {
        setMatches(data.matches);
      } else {
        setMatches((prev) => [...prev, ...data.matches]);
      }
      setHasMore(data.hasMore);
    } catch (e) {
      console.error("Failed to load matches:", e);
    } finally {
      setLoading(false);
    }
  }

  onMount(() => loadMatches());

  function loadMore() {
    loadMatches(matches().length);
  }

  function formatRoll(roll: number | null): string {
    if (roll === null) return "-";
    return roll.toFixed(3);
  }

  function formatTime(iso: string | null): string {
    if (!iso) return "-";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function eloChange(m: MatchResponse): number | null {
    if (m.playerEloBefore === null || m.playerEloAfter === null) return null;
    return m.playerEloAfter - m.playerEloBefore;
  }

  return (
    <div class="flex-1 flex flex-col items-center p-6 max-w-2xl mx-auto w-full">
      <h2 class="text-2xl font-bold mb-6">Match History</h2>

      <Show when={loading()}>
        <div class="animate-pulse text-gray-400">Loading...</div>
      </Show>

      <Show when={!loading() && matches().length === 0}>
        <div class="text-center text-gray-500">
          <p class="mb-4">No matches yet.</p>
          <button
            onClick={() => navigate("/")}
            class="px-6 py-2 bg-brand hover:bg-brand-light rounded-lg transition-colors text-white"
          >
            Play Now
          </button>
        </div>
      </Show>

      <Show when={!loading() && matches().length > 0}>
        <div class="w-full space-y-2">
          <For each={matches()}>
            {(m) => {
              const change = eloChange(m);
              return (
                <div class="flex items-center gap-4 px-4 py-3 bg-gray-900 rounded-lg border border-gray-800">
                  {}
                  <div
                    class={`w-2 h-8 rounded-full ${
                      m.won === true
                        ? "bg-green-500"
                        : m.won === false
                          ? "bg-red-500"
                          : "bg-gray-600"
                    }`}
                  />

                  {}
                  <div class="flex-1 min-w-0">
                    <div class="font-semibold truncate">vs {m.opponentName}</div>
                    <div class="text-xs text-gray-500">
                      {m.isPractice ? "Practice" : "Ranked"} · {formatTime(m.completedAt)}
                    </div>
                  </div>

                  {}
                  <div class="text-right text-sm font-mono tabular-nums">
                    <span class={m.won === true ? "text-green-400" : "text-white"}>
                      {formatRoll(m.playerRoll)}
                    </span>
                    <span class="text-gray-600 mx-1">vs</span>
                    <span class={m.won === false ? "text-green-400" : "text-white"}>
                      {formatRoll(m.opponentRoll)}
                    </span>
                  </div>

                  {}
                  <div class="w-16 text-right text-sm font-semibold">
                    <Show
                      when={change !== null && !m.isPractice}
                      fallback={<span class="text-gray-600">—</span>}
                    >
                      <span class={change! >= 0 ? "text-green-400" : "text-red-400"}>
                        {change! >= 0 ? "+" : ""}
                        {change}
                      </span>
                    </Show>
                  </div>
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

export default History;
