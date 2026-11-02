import type { Component } from "solid-js";
import { useNavigate } from "@solidjs/router";
import PlayerStats from "../components/PlayerStats";
import UsernameEditor from "../components/UsernameEditor";
import { api } from "../services/api";
import { signalr } from "../services/signalr";
import { gameStore } from "../stores/gameStore";
import { authStore } from "../stores/authStore";

const Lobby: Component = () => {
  const navigate = useNavigate();

  async function startPractice() {
    try {
      const result = await api.startPractice();
      gameStore.setMatchFound(result.matchId, result.opponentName, true);
      await signalr.joinMatch(result.matchId);
      navigate(`/game/${result.matchId}`);
    } catch (e) {
      console.error("Failed to start practice:", e);
    }
  }

  async function startMultiplayer() {
    try {
      gameStore.setQueuing();
      await signalr.joinQueue();
      navigate("/matchmaking");
    } catch (e) {
      console.error("Failed to join queue:", e);
      gameStore.reset();
    }
  }

  return (
    <div class="flex-1 flex flex-col items-center justify-center gap-8 p-6">
      <div class="text-center">
        <h1 class="text-5xl font-black text-brand mb-2">RNGWars</h1>
        <p class="text-gray-500">May the RNG be ever in your favor</p>
      </div>

      <UsernameEditor />
      <PlayerStats />

      <div class="flex flex-col gap-3 w-64">
        <button
          onClick={startPractice}
          disabled={!authStore.signalrConnected()}
          class="w-full py-3 px-6 bg-gray-800 hover:bg-gray-700 border border-gray-600 rounded-lg text-lg font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Practice
        </button>
        <button
          onClick={startMultiplayer}
          disabled={!authStore.signalrConnected()}
          class="w-full py-3 px-6 bg-brand hover:bg-brand-light rounded-lg text-lg font-semibold transition-colors text-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Multiplayer
        </button>
      </div>
    </div>
  );
};

export default Lobby;
