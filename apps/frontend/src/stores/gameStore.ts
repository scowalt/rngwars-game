import { createStore } from "solid-js/store";
import type { GameState } from "../types";

const initialState: GameState = {
  phase: "idle",
  matchId: null,
  opponentName: null,
  queuePosition: null,
  countdownValue: null,
  timeRemaining: null,
  playerRoll: null,
  opponentRoll: null,
  winnerId: null,
  eloChange: null,
  newElo: null,
  isPractice: false,
  errorMessage: null,
};

const [state, setState] = createStore<GameState>({ ...initialState });

function reset() {
  setState({ ...initialState });
}

function setQueuing() {
  setState({ phase: "queuing", queuePosition: null });
}

function setQueuePosition(position: number) {
  setState({ queuePosition: position });
}

function setMatchFound(matchId: string, opponentName: string, isPractice: boolean) {
  setState({
    phase: "connecting",
    matchId,
    opponentName,
    isPractice,
  });
}

function setCountdown(count: number, timeRemaining: number) {
  setState({
    phase: "countdown",
    countdownValue: count,
    timeRemaining,
  });
}

function setRolling(timeRemaining: number) {
  setState({ phase: "rolling", timeRemaining });
}

function setRevealed(playerRoll: number, opponentRoll: number, timeRemaining: number) {
  setState({
    phase: "revealed",
    playerRoll,
    opponentRoll,
    timeRemaining,
  });
}

function setCompleted(winnerId: string, eloChange: number, newElo: number) {
  setState({
    phase: "completed",
    winnerId,
    eloChange,
    newElo,
  });
}

function setCancelled(message: string) {
  setState({
    phase: "cancelled",
    errorMessage: message,
  });
}

export const gameStore = {
  state,
  reset,
  setQueuing,
  setQueuePosition,
  setMatchFound,
  setCountdown,
  setRolling,
  setRevealed,
  setCompleted,
  setCancelled,
};
