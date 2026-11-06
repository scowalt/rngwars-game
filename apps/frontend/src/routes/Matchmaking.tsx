import type { Component } from "solid-js";
import { Show, createEffect } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { signalr } from "../services/signalr";
import { gameStore } from "../stores/gameStore";

const Matchmaking: Component = () => {
  const navigate = useNavigate();

  createEffect(() => {
    if (gameStore.state.phase === "connecting" && gameStore.state.matchId) {
      signalr.joinMatch(gameStore.state.matchId).catch(console.error);
      navigate(`/game/${gameStore.state.matchId}`);
    }
  });

  createEffect(() => {
    if (gameStore.state.phase !== "queuing" && !gameStore.state.matchId) {
      navigate("/");
    }
  });

  async function leaveQueue() {
    try {
      await signalr.leaveQueue();
    } catch (e) {
      console.error("Failed to leave queue:", e);
    }
    gameStore.reset();
    navigate("/");
  }

  return (
    <div class="flex-1 flex flex-col items-center justify-center p-6">
      <div class="text-center">
        <h2 class="text-2xl font-bold mb-4">Finding Opponent...</h2>
        <div class="animate-pulse text-6xl mb-6">🎲</div>
        <Show when={gameStore.state.queuePosition !== null}>
          <p class="text-gray-400 mb-4">Position in queue: {gameStore.state.queuePosition}</p>
        </Show>
        <button
          onClick={leaveQueue}
          class="px-6 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

export default Matchmaking;
