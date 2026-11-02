import type {
  User,
  CreateAnonymousResponse,
  MatchListResponse,
  MatchResponse,
  LeaderboardResponse,
  PracticeStartResponse,
  ApiError,
} from "../types";

const BASE_URL = "/api";

class ApiClient {
  private token: string | null = null;

  setToken(token: string) {
    this.token = token;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let error: ApiError;
      try {
        error = await response.json();
      } catch {
        error = {
          error: {
            code: `HTTP_${response.status}`,
            message: response.statusText || `Request failed with status ${response.status}`,
          },
        };
      }
      throw error;
    }

    if (response.status === 204) {
      return undefined as T;
    }

    try {
      return await response.json();
    } catch {
      return undefined as T;
    }
  }

  async createAnonymousUser(): Promise<CreateAnonymousResponse> {
    return this.request("/users/anonymous", { method: "POST" });
  }

  async getMe(): Promise<User> {
    return this.request("/users/me");
  }

  async updateUsername(username: string): Promise<User> {
    return this.request("/users/me", {
      method: "PUT",
      body: JSON.stringify({ username }),
    });
  }

  async getMatches(offset: number = 0, limit: number = 20): Promise<MatchListResponse> {
    return this.request(`/users/me/matches?offset=${offset}&limit=${limit}`);
  }

  async getMatch(matchId: string): Promise<MatchResponse> {
    return this.request(`/matches/${matchId}`);
  }

  async getLeaderboard(offset: number = 0, limit: number = 20): Promise<LeaderboardResponse> {
    return this.request(`/leaderboard?offset=${offset}&limit=${limit}`);
  }

  async startPractice(): Promise<PracticeStartResponse> {
    return this.request("/matches/practice", { method: "POST" });
  }
}

export const api = new ApiClient();
