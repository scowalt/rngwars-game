import type { Component } from "solid-js";
import { authStore } from "../stores/authStore";

const PlayerStats: Component = () => {
  const user = authStore.user;

  return (
    <div class="flex gap-6 text-sm">
      <div class="text-center">
        <div class="text-2xl font-bold text-brand">{user()?.rngScore ?? "—"}</div>
        <div class="text-gray-500 uppercase tracking-wide text-xs">RNG Score</div>
      </div>
      <div class="text-center">
        <div class="text-2xl font-bold text-green-400">{user()?.totalWins ?? 0}</div>
        <div class="text-gray-500 uppercase tracking-wide text-xs">Wins</div>
      </div>
      <div class="text-center">
        <div class="text-2xl font-bold text-red-400">{user()?.totalLosses ?? 0}</div>
        <div class="text-gray-500 uppercase tracking-wide text-xs">Losses</div>
      </div>
    </div>
  );
};

export default PlayerStats;
