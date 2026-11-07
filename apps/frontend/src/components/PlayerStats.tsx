import type { Component } from "solid-js";
import { authStore } from "../stores/authStore";

const PlayerStats: Component = () => {
  const user = authStore.user;

  return (
    <div class="player-stats">
      <div class="player-stat">
        <div class="player-stat-value player-stat-score">{user()?.rngScore ?? "—"}</div>
        <div class="player-stat-label">RNG Score</div>
      </div>
      <div class="player-stat">
        <div class="player-stat-value player-stat-wins">{user()?.totalWins ?? 0}</div>
        <div class="player-stat-label">Wins</div>
      </div>
      <div class="player-stat">
        <div class="player-stat-value player-stat-losses">{user()?.totalLosses ?? 0}</div>
        <div class="player-stat-label">Losses</div>
      </div>
    </div>
  );
};

export default PlayerStats;
