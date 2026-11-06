import { Component, ErrorBoundary, Show, createSignal, onMount } from "solid-js";
import * as Sentry from "@sentry/browser";
import { Router, Route } from "@solidjs/router";
import Layout from "./components/Layout";
import Lobby from "./routes/Lobby";
import Game from "./routes/Game";
import History from "./routes/History";
import Leaderboard from "./routes/Leaderboard";
import Matchmaking from "./routes/Matchmaking";
import { authStore } from "./stores/authStore";
import { signalr } from "./services/signalr";
import { gameStore } from "./stores/gameStore";

function setupSignalREvents() {
  signalr.on("onQueueUpdate", (data) => {
    gameStore.setQueuePosition(data.position);
  });

  signalr.on("onMatchFound", (data) => {
    gameStore.setMatchFound(data.matchId, data.opponentName, false);
  });

  signalr.on("onPhaseChanged", (data) => {
    switch (data.phase) {
      case "countdown":
        gameStore.setCountdown(data.count, data.timeRemaining);
        break;
      case "rolling":
        gameStore.setRolling(data.timeRemaining);
        break;
      case "revealed": {
        const userId = authStore.user()?.id;
        const isP1 = userId === data.player1Id;
        const myRoll = isP1 ? data.player1Roll : data.player2Roll;
        const theirRoll = isP1 ? data.player2Roll : data.player1Roll;
        gameStore.setRevealed(myRoll, theirRoll, data.timeRemaining);
        break;
      }
    }
  });

  signalr.on("onMatchCompleted", (data) => {
    const userId = authStore.user()?.id;
    const isPlayer1 = userId === data.player1Id;
    const eloChange = isPlayer1 ? data.player1EloChange : data.player2EloChange;
    const newElo = isPlayer1 ? data.player1NewElo : data.player2NewElo;
    gameStore.setCompleted(data.winnerId, eloChange, newElo);
  });

  signalr.on("onMatchCancelled", (data) => {
    gameStore.setCancelled(data.error.message);
  });

  signalr.on("onReconnected", () => {
    if (gameStore.state.phase === "queuing") {
      signalr.joinQueue().catch(console.error);
    }
  });
}

const App: Component = () => {
  const [startupFailed, setStartupFailed] = createSignal(false);

  function initialize() {
    setStartupFailed(false);
    void authStore.initialize().catch(() => setStartupFailed(true));
  }

  onMount(() => {
    setupSignalREvents();
    initialize();
  });

  return (
    <ErrorBoundary
      fallback={(err, reset) => {
        Sentry.captureException(err);
        return (
          <div class="min-h-screen flex flex-col items-center justify-center gap-4">
            <p class="text-xl text-red-400">Something went wrong.</p>
            <button
              class="px-4 py-2 bg-brand text-white rounded hover:opacity-90"
              onClick={() => {
                reset();
                window.location.reload();
              }}
            >
              Reload
            </button>
          </div>
        );
      }}
    >
      <Show
        when={!startupFailed()}
        fallback={
          <div class="min-h-screen flex flex-col items-center justify-center gap-4 px-6 text-center">
            <p class="text-xl text-red-400">Unable to initialize your player profile.</p>
            <button
              class="px-4 py-2 bg-brand text-white rounded hover:opacity-90"
              onClick={initialize}
            >
              Retry
            </button>
          </div>
        }
      >
        <Show
          when={!authStore.loading()}
          fallback={
            <div class="min-h-screen flex items-center justify-center">
              <div class="animate-pulse text-xl text-gray-400">Loading...</div>
            </div>
          }
        >
          <Router root={Layout}>
            <Route path="/" component={Lobby} />
            <Route path="/game/:matchId" component={Game} />
            <Route path="/history" component={History} />
            <Route path="/leaderboard" component={Leaderboard} />
            <Route path="/matchmaking" component={Matchmaking} />
          </Router>
        </Show>
      </Show>
    </ErrorBoundary>
  );
};

export default App;
