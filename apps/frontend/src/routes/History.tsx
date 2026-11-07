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
    <div class="page-column">
      <h2 class="page-title">Match History</h2>

      <Show when={loading()}>
        <div class="loading-text">Loading...</div>
      </Show>

      <Show when={!loading() && matches().length === 0}>
        <div class="history-empty">
          <p class="history-empty-message">No matches yet.</p>
          <button onClick={() => navigate("/")} class="button button-primary">
            Play Now
          </button>
        </div>
      </Show>

      <Show when={!loading() && matches().length > 0}>
        <div class="history-list">
          <For each={matches()}>
            {(m) => {
              const change = eloChange(m);
              return (
                <div class="list-row history-row">
                  {}
                  <div
                    class={
                      m.won === true
                        ? "result-marker result-marker-win"
                        : m.won === false
                          ? "result-marker result-marker-loss"
                          : "result-marker"
                    }
                  />

                  {}
                  <div class="history-details">
                    <div class="history-opponent">vs {m.opponentName}</div>
                    <div class="history-meta">
                      {m.isPractice ? "Practice" : "Ranked"} · {formatTime(m.completedAt)}
                    </div>
                  </div>

                  {}
                  <div class="history-rolls">
                    <span
                      class={m.won === true ? "history-roll history-roll-winner" : "history-roll"}
                    >
                      {formatRoll(m.playerRoll)}
                    </span>
                    <span class="history-roll-versus">vs</span>
                    <span
                      class={m.won === false ? "history-roll history-roll-winner" : "history-roll"}
                    >
                      {formatRoll(m.opponentRoll)}
                    </span>
                  </div>

                  {}
                  <div class="history-elo">
                    <Show
                      when={change !== null && !m.isPractice}
                      fallback={<span class="history-elo-none">—</span>}
                    >
                      <span class={change! >= 0 ? "history-elo-gain" : "history-elo-loss"}>
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
          <button onClick={loadMore} class="button button-secondary load-more">
            Load More
          </button>
        </Show>
      </Show>
    </div>
  );
};

export default History;
