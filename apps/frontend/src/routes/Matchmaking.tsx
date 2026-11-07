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
    <div class="stage">
      <div class="stage-panel">
        <h2 class="matchmaking-heading">Finding Opponent...</h2>
        <div class="stage-emoji stage-emoji-pulsing">🎲</div>
        <Show when={gameStore.state.queuePosition !== null}>
          <p class="queue-position">Position in queue: {gameStore.state.queuePosition}</p>
        </Show>
        <button onClick={leaveQueue} class="button button-muted">
          Cancel
        </button>
      </div>
    </div>
  );
};

export default Matchmaking;
