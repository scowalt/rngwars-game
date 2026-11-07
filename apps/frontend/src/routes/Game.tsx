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
    <div class="stage">
      {}
      <Show when={gameStore.state.phase === "connecting"}>
        <div class="stage-panel">
          <div class="stage-emoji stage-emoji-pulsing">⚔️</div>
          <h2 class="game-heading">Connecting...</h2>
          <p class="opponent-line">
            vs <span class="opponent-name">{gameStore.state.opponentName}</span>
          </p>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "countdown"}>
        <div class="stage-panel game-countdown">
          <p class="opponent-line">
            vs <span class="opponent-name">{gameStore.state.opponentName}</span>
          </p>
          <div class="countdown-value">{gameStore.state.countdownValue}</div>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "rolling"}>
        <div class="stage-panel game-rolling">
          <p class="opponent-line">
            vs <span class="opponent-name">{gameStore.state.opponentName}</span>
          </p>
          <div class="roll-matchup">
            <RollDisplay label="You" value={playerRolling()} highlight={false} />
            <div class="roll-versus">vs</div>
            <RollDisplay
              label={gameStore.state.opponentName ?? "Opponent"}
              value={opponentRolling()}
              highlight={false}
            />
          </div>
          <p class="rolling-hint">Rolling...</p>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "revealed"}>
        <div class="stage-panel game-revealed">
          <p class="opponent-line">
            vs <span class="opponent-name">{gameStore.state.opponentName}</span>
          </p>
          <div class="roll-matchup">
            <RollDisplay
              label="You"
              value={formatRoll(gameStore.state.playerRoll)}
              highlight={
                gameStore.state.playerRoll !== null &&
                gameStore.state.opponentRoll !== null &&
                gameStore.state.playerRoll > gameStore.state.opponentRoll
              }
            />
            <div class="roll-versus">vs</div>
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
        <div class="stage-panel game-completed">
          <div class="stage-emoji">{isWinner() ? "🏆" : "💀"}</div>
          <h2
            class={`result-heading ${isWinner() ? "result-heading-victory" : "result-heading-defeat"}`}
          >
            {isWinner() ? "Victory!" : "Defeat"}
          </h2>
          <p class="opponent-line">
            vs <span class="opponent-name">{gameStore.state.opponentName}</span>
          </p>

          <div class="roll-matchup">
            <RollDisplay
              label="You"
              value={formatRoll(gameStore.state.playerRoll)}
              highlight={isWinner()}
            />
            <div class="roll-versus">vs</div>
            <RollDisplay
              label={gameStore.state.opponentName ?? "Opponent"}
              value={formatRoll(gameStore.state.opponentRoll)}
              highlight={!isWinner()}
            />
          </div>

          <Show when={!gameStore.state.isPractice && gameStore.state.eloChange !== null}>
            <div class="elo-summary">
              <span
                class={`elo-change ${(gameStore.state.eloChange ?? 0) >= 0 ? "elo-change-gain" : "elo-change-loss"}`}
              >
                {(gameStore.state.eloChange ?? 0) >= 0 ? "+" : ""}
                {gameStore.state.eloChange}
              </span>
              <span class="elo-total">ELO ({gameStore.state.newElo})</span>
            </div>
          </Show>

          <Show when={gameStore.state.isPractice}>
            <p class="practice-note">Practice — no ELO change</p>
          </Show>

          <button onClick={playAgain} class="button button-primary button-large">
            Play Again
          </button>
        </div>
      </Show>

      {}
      <Show when={gameStore.state.phase === "cancelled"}>
        <div class="stage-panel">
          <div class="stage-emoji">❌</div>
          <h2 class="game-heading game-heading-cancelled">Match Cancelled</h2>
          <p class="cancel-reason">{gameStore.state.errorMessage}</p>
          <button onClick={playAgain} class="button button-muted button-large">
            Back to Lobby
          </button>
        </div>
      </Show>
    </div>
  );
};

function RollDisplay(props: { label: string; value: string; highlight: boolean }) {
  return (
    <div class="roll">
      <span class="roll-label">{props.label}</span>
      <span class={props.highlight ? "roll-value roll-value-winner" : "roll-value"}>
        {props.value}
      </span>
    </div>
  );
}

export default Game;
