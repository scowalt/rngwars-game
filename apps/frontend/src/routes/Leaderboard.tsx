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
    <div class="page-column">
      <h2 class="page-title">Leaderboard</h2>

      <Show when={loading()}>
        <div class="loading-text">Loading...</div>
      </Show>

      <Show when={!loading() && entries().length === 0}>
        <p class="leaderboard-empty">No ranked players yet. Play a match to get on the board!</p>
      </Show>

      <Show when={!loading() && entries().length > 0}>
        {}
        <div class="leaderboard-header">
          <div>#</div>
          <div>Player</div>
          <div class="leaderboard-numeric">ELO</div>
          <div class="leaderboard-numeric">W / L</div>
          <div class="leaderboard-numeric">Win%</div>
        </div>

        <div class="leaderboard-list">
          <For each={entries()}>
            {(entry) => {
              const isMe = () => entry.userId === authStore.user()?.id;
              return (
                <div
                  class={
                    isMe()
                      ? "list-row leaderboard-row leaderboard-row-me"
                      : "list-row leaderboard-row"
                  }
                >
                  {}
                  <div class="leaderboard-rank">
                    {entry.rank <= 3 ? (
                      <span
                        class={
                          entry.rank === 1
                            ? "medal-gold"
                            : entry.rank === 2
                              ? "medal-silver"
                              : "medal-bronze"
                        }
                      >
                        {entry.rank === 1 ? "🥇" : entry.rank === 2 ? "🥈" : "🥉"}
                      </span>
                    ) : (
                      entry.rank
                    )}
                  </div>

                  {}
                  <div class="leaderboard-player">
                    <span
                      class={isMe() ? "leaderboard-name leaderboard-name-me" : "leaderboard-name"}
                    >
                      {entry.username}
                    </span>
                    <Show when={isMe()}>
                      <span class="leaderboard-you">(you)</span>
                    </Show>
                  </div>

                  {}
                  <div class="leaderboard-numeric leaderboard-elo">{entry.rngScore}</div>

                  {}
                  <div class="leaderboard-numeric leaderboard-record">
                    <span class="record-wins">{entry.totalWins}</span>
                    <span class="record-separator"> / </span>
                    <span class="record-losses">{entry.totalLosses}</span>
                  </div>

                  {}
                  <div class="leaderboard-numeric leaderboard-win-rate">{winRate(entry)}</div>
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

export default Leaderboard;
