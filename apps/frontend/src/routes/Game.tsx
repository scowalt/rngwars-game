import { Component, Show, Switch, Match, createEffect, createSignal, onCleanup } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { gameStore } from "../stores/gameStore";
import { authStore } from "../stores/authStore";

const Game: Component = () => {
  const navigate = useNavigate();
  const [playerRolling, setPlayerRolling] = createSignal("00.000");
  const [opponentRolling, setOpponentRolling] = createSignal("00.000");

  let rollingInterval: ReturnType<typeof setInterval> | undefined;

  createEffect(() => {
    if (gameStore.state.phase === "rolling") {
      rollingInterval = setInterval(() => {
        setPlayerRolling((Math.random() * 100).toFixed(3));
        setOpponentRolling((Math.random() * 100).toFixed(3));
      }, 50);
    } else {
      if (rollingInterval) {
        clearInterval(rollingInterval);
        rollingInterval = undefined;
      }
    }
  });

  onCleanup(() => {
    if (rollingInterval) clearInterval(rollingInterval);
  });

  function isWinner() {
    return gameStore.state.winnerId === authStore.user()?.id;
  }

  function formatRoll(roll: number | null): string {
    if (roll === null) return "00.000";
    return roll.toFixed(3);
  }

  function playAgain() {
    gameStore.reset();
    authStore.refreshUser();
    navigate("/");
  }

  createEffect(() => {
    if (gameStore.state.phase === "idle" && !gameStore.state.matchId) {
      navigate("/");
    }
  });

  return (
    <div class="flex-1 flex flex-col items-center justify-center p-6">
      {}
      <Show when={gameStore.state.phase === "connecting"}>
        <div class="text-center">
          <div class="animate-pulse text-6xl mb-6">⚔️</div>
          <h2 class="text-2xl font-bold mb-2">Connecting...</h2>
          <p class="text-gray-400">
            vs <span class="text-brand font-semibold">{gameStore.state.opponentName}</span>
          </p>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "countdown"}>
        <div class="text-center">
          <p class="text-gray-400 mb-2">
            vs <span class="text-brand font-semibold">{gameStore.state.opponentName}</span>
          </p>
          <div class="text-9xl font-black text-brand animate-pulse">
            {gameStore.state.countdownValue}
          </div>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "rolling"}>
        <div class="text-center">
          <p class="text-gray-400 mb-6">
            vs <span class="text-brand font-semibold">{gameStore.state.opponentName}</span>
          </p>
          <div class="flex items-center justify-center gap-12">
            <RollDisplay label="You" value={playerRolling()} highlight={false} />
            <div class="text-3xl font-bold text-gray-600">vs</div>
            <RollDisplay
              label={gameStore.state.opponentName ?? "Opponent"}
              value={opponentRolling()}
              highlight={false}
            />
          </div>
          <p class="text-gray-500 mt-6 animate-pulse">Rolling...</p>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "revealed"}>
        <div class="text-center">
          <p class="text-gray-400 mb-6">
            vs <span class="text-brand font-semibold">{gameStore.state.opponentName}</span>
          </p>
          <div class="flex items-center justify-center gap-12">
            <RollDisplay
              label="You"
              value={formatRoll(gameStore.state.playerRoll)}
              highlight={
                gameStore.state.playerRoll !== null &&
                gameStore.state.opponentRoll !== null &&
                gameStore.state.playerRoll > gameStore.state.opponentRoll
              }
            />
            <div class="text-3xl font-bold text-gray-600">vs</div>
            <RollDisplay
              label={gameStore.state.opponentName ?? "Opponent"}
              value={formatRoll(gameStore.state.opponentRoll)}
              highlight={
                gameStore.state.playerRoll !== null &&
                gameStore.state.opponentRoll !== null &&
                gameStore.state.opponentRoll > gameStore.state.playerRoll
              }
            />
          </div>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "completed"}>
        <div class="text-center">
          <div class="text-6xl mb-4">{isWinner() ? "🏆" : "💀"}</div>
          <h2 class={`text-4xl font-black mb-2 ${isWinner() ? "text-green-400" : "text-red-400"}`}>
            {isWinner() ? "Victory!" : "Defeat"}
          </h2>
          <p class="text-gray-400 mb-6">
            vs <span class="text-brand font-semibold">{gameStore.state.opponentName}</span>
          </p>

          <div class="flex items-center justify-center gap-12 mb-8">
            <RollDisplay
              label="You"
              value={formatRoll(gameStore.state.playerRoll)}
              highlight={isWinner()}
            />
            <div class="text-3xl font-bold text-gray-600">vs</div>
            <RollDisplay
              label={gameStore.state.opponentName ?? "Opponent"}
              value={formatRoll(gameStore.state.opponentRoll)}
              highlight={!isWinner()}
            />
          </div>

          <Show when={!gameStore.state.isPractice && gameStore.state.eloChange !== null}>
            <div class="mb-6">
              <span
                class={`text-2xl font-bold ${(gameStore.state.eloChange ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}
              >
                {(gameStore.state.eloChange ?? 0) >= 0 ? "+" : ""}
                {gameStore.state.eloChange}
              </span>
              <span class="text-gray-500 ml-2">ELO ({gameStore.state.newElo})</span>
            </div>
          </Show>

          <Show when={gameStore.state.isPractice}>
            <p class="text-gray-500 mb-6 text-sm">Practice — no ELO change</p>
          </Show>

          <button
            onClick={playAgain}
            class="px-8 py-3 bg-brand hover:bg-brand-light rounded-lg text-lg font-semibold transition-colors text-white"
          >
            Play Again
          </button>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "cancelled"}>
        <div class="text-center">
          <div class="text-6xl mb-4">❌</div>
          <h2 class="text-2xl font-bold mb-2 text-red-400">Match Cancelled</h2>
          <p class="text-gray-400 mb-6">{gameStore.state.errorMessage}</p>
          <button
            onClick={playAgain}
            class="px-8 py-3 bg-gray-700 hover:bg-gray-600 rounded-lg text-lg font-semibold transition-colors"
          >
            Back to Lobby
          </button>
        </div>
      </Show>
    </div>
  );
};

function RollDisplay(props: { label: string; value: string; highlight: boolean }) {
  return (
    <div class="flex flex-col items-center">
      <span class="text-sm text-gray-500 mb-1">{props.label}</span>
      <span
        class={`text-5xl font-mono font-bold tabular-nums ${props.highlight ? "text-green-400" : "text-white"}`}
      >
        {props.value}
      </span>
    </div>
  );
}

export default Game;
