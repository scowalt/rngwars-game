export interface User {
  id: string;
  username: string;
  avatarUrl: string | null;
  isAnonymous: boolean;
  rngScore: number;
  totalWins: number;
  totalLosses: number;
  totalMatches: number;
}

export interface CreateAnonymousResponse {
  token: string;
  user: User;
}

export interface MatchResponse {
  id: string;
  opponentName: string;
  opponentElo: number | null;
  playerRoll: number | null;
  opponentRoll: number | null;
  playerEloBefore: number | null;
  playerEloAfter: number | null;
  won: boolean | null;
  isPractice: boolean;
  status: string;
  completedAt: string | null;
}

export interface MatchListResponse {
  matches: MatchResponse[];
  hasMore: boolean;
}

export interface LeaderboardEntry {
  rank: number;
  userId: string;
  username: string;
  rngScore: number;
  totalWins: number;
  totalLosses: number;
  totalMatches: number;
}

export interface LeaderboardResponse {
  entries: LeaderboardEntry[];
  hasMore: boolean;
}

export interface PracticeStartResponse {
  matchId: string;
  opponentName: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
  };
}

export interface QueueUpdate {
  position: number;
  estimatedWait: number;
}

export interface MatchFound {
  matchId: string;
  opponentName: string;
}

export type PhaseChanged =
  | { phase: "countdown"; timeRemaining: number; count: number }
  | { phase: "rolling"; timeRemaining: number }
  | {
      phase: "revealed";
      timeRemaining: number;
      player1Id: string;
      player1Roll: number;
      player2Roll: number;
    };

export interface MatchCompleted {
  winnerId: string;
  player1Id: string;
  player1EloChange: number;
  player1NewElo: number;
  player2EloChange: number;
  player2NewElo: number;
}

export interface MatchCancelled {
  error: {
    code: string;
    message: string;
  };
}

export type GamePhase =
  | "idle"
  | "queuing"
  | "connecting"
  | "countdown"
  | "rolling"
  | "revealed"
  | "completed"
  | "cancelled";

export interface GameState {
  phase: GamePhase;
  matchId: string | null;
  opponentName: string | null;
  queuePosition: number | null;
  countdownValue: number | null;
  timeRemaining: number | null;
  playerRoll: number | null;
  opponentRoll: number | null;
  winnerId: string | null;
  eloChange: number | null;
  newElo: number | null;
  isPractice: boolean;
  errorMessage: string | null;
}
