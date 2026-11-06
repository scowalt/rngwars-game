import { afterEach, describe, expect, test, vi } from "vitest";
import { render } from "solid-js/web";

const { apiMock, signalrMock } = vi.hoisted(() => ({
  apiMock: {
    createAnonymousUser: vi.fn().mockResolvedValue({
      token: "11111111-1111-4111-8111-111111111111",
      user: {
        id: "22222222-2222-4222-8222-222222222222",
        username: "Test Pilot",
        avatarUrl: null,
        isAnonymous: true,
        rngScore: 1200,
        totalWins: 2,
        totalLosses: 1,
        totalMatches: 3,
      },
    }),
    getMe: vi.fn(),
    setToken: vi.fn(),
    startPractice: vi.fn(),
    updateUsername: vi.fn(),
  },
  signalrMock: {
    connect: vi.fn().mockResolvedValue(undefined),
    joinMatch: vi.fn().mockResolvedValue(undefined),
    joinQueue: vi.fn(),
    on: vi.fn(),
  },
}));

vi.mock("./services/api", () => ({ api: apiMock }));
vi.mock("./services/signalr", () => ({ signalr: signalrMock }));

import App from "./App";
import { gameStore } from "./stores/gameStore";

function emit(event: string, data?: unknown) {
  for (const [name, handler] of signalrMock.on.mock.calls) {
    if (name === event) handler(data);
  }
}

async function clickMultiplayer(root: HTMLElement) {
  const button = await vi.waitFor(() => {
    emit("onConnected");
    const found = [...root.querySelectorAll("button")].find(
      (b) => b.textContent === "Multiplayer" && !b.disabled
    );
    expect(found).toBeDefined();
    return found!;
  });
  button.click();
}

describe("application startup", () => {
  let dispose: (() => void) | undefined;

  afterEach(() => {
    dispose?.();
    dispose = undefined;
    localStorage.clear();
    document.body.replaceChildren();
    gameStore.reset();
    vi.clearAllMocks();
  });

  test("shows the authenticated lobby after anonymous startup", async () => {
    window.history.replaceState({}, "", "/");
    const root = document.createElement("div");
    document.body.append(root);

    dispose = render(() => <App />, root);

    await vi.waitFor(() => {
      expect(root.textContent).toContain("Test Pilot");
    });
  });

  test("handles anonymous startup failure without an unhandled rejection", async () => {
    const startupFailure = {
      error: { code: "HTTP_500", message: "Internal Server Error" },
    };
    apiMock.createAnonymousUser.mockRejectedValueOnce(startupFailure);
    const onUnhandledRejection = vi.fn();
    window.addEventListener("unhandledrejection", onUnhandledRejection);

    window.history.replaceState({}, "", "/");
    const root = document.createElement("div");
    document.body.append(root);

    dispose = render(() => <App />, root);

    await vi.waitFor(() => {
      expect(root.textContent).toContain("Unable to initialize your player profile.");
    });
    expect(onUnhandledRejection).not.toHaveBeenCalled();

    window.removeEventListener("unhandledrejection", onUnhandledRejection);
  });

  test("redirects to the lobby when opening matchmaking without an active queue", async () => {
    window.history.replaceState({}, "", "/matchmaking");
    const root = document.createElement("div");
    document.body.append(root);

    dispose = render(() => <App />, root);

    await vi.waitFor(() => {
      expect(window.location.pathname).toBe("/");
      expect(root.textContent).toContain("Multiplayer");
    });
    expect(root.textContent).not.toContain("Finding Opponent...");
  });

  test("waits in matchmaking after queuing from the lobby until a match is found", async () => {
    signalrMock.joinQueue.mockResolvedValueOnce(undefined);
    window.history.replaceState({}, "", "/");
    const root = document.createElement("div");
    document.body.append(root);

    dispose = render(() => <App />, root);
    await clickMultiplayer(root);

    await vi.waitFor(() => {
      expect(window.location.pathname).toBe("/matchmaking");
      expect(root.textContent).toContain("Finding Opponent...");
    });

    emit("onMatchFound", { matchId: "match-1", opponentName: "Rival" });

    await vi.waitFor(() => {
      expect(window.location.pathname).toBe("/game/match-1");
    });
    expect(signalrMock.joinMatch).toHaveBeenCalledWith("match-1");
  });

  test("joins the match when it is found before reaching matchmaking", async () => {
    signalrMock.joinQueue.mockImplementationOnce(async () => {
      emit("onMatchFound", { matchId: "match-2", opponentName: "Rival" });
    });
    window.history.replaceState({}, "", "/");
    const root = document.createElement("div");
    document.body.append(root);

    dispose = render(() => <App />, root);
    await clickMultiplayer(root);

    await vi.waitFor(() => {
      expect(window.location.pathname).toBe("/game/match-2");
    });
    expect(signalrMock.joinMatch).toHaveBeenCalledWith("match-2");
  });
});
