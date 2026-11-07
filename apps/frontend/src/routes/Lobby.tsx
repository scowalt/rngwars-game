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
    <div class="stage lobby">
      <div class="stage-panel">
        <h1 class="lobby-title">RNGWars</h1>
        <p class="lobby-tagline">May the RNG be ever in your favor</p>
      </div>

      <UsernameEditor />
      <PlayerStats />

      <div class="lobby-actions">
        <button
          onClick={startPractice}
          disabled={!authStore.signalrConnected()}
          class="button button-secondary lobby-action"
        >
          Practice
        </button>
        <button
          onClick={startMultiplayer}
          disabled={!authStore.signalrConnected()}
          class="button button-primary lobby-action"
        >
          Multiplayer
        </button>
      </div>
    </div>
  );
};

export default Lobby;
