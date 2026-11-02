import { createSignal } from "solid-js";
import * as Sentry from "@sentry/browser";
import posthog from "posthog-js";
import type { User } from "../types";
import { api } from "../services/api";
import { signalr } from "../services/signalr";

const TOKEN_KEY = "rngwars_token";

const [user, setUser] = createSignal<User | null>(null);
const [loading, setLoading] = createSignal(true);
const [signalrConnected, setSignalrConnected] = createSignal(false);

function isValidUUID(token: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(token);
}

async function initialize(): Promise<void> {
  setLoading(true);
  try {
    const storedToken = localStorage.getItem(TOKEN_KEY);

    if (storedToken && isValidUUID(storedToken)) {
      api.setToken(storedToken);
      try {
        const userData = await api.getMe();
        setUser(userData);
        identifyUser(userData);
        connectSignalR(storedToken);
        return;
      } catch {
        localStorage.removeItem(TOKEN_KEY);
      }
    }

    const response = await api.createAnonymousUser();
    localStorage.setItem(TOKEN_KEY, response.token);
    api.setToken(response.token);
    setUser(response.user);
    identifyUser(response.user);
    connectSignalR(response.token);
  } finally {
    setLoading(false);
  }
}

function identifyUser(u: User) {
  Sentry.setUser({ id: u.id, username: u.username });
  if (posthog.__loaded) {
    posthog.identify(u.id, {
      username: u.username,
      is_anonymous: u.isAnonymous,
      elo: u.rngScore,
    });
  }
}

function connectSignalR(token: string) {
  signalr.on("onConnected", () => setSignalrConnected(true));
  signalr.on("onDisconnected", () => setSignalrConnected(false));
  signalr.connect(token).catch(console.error);
}

async function updateUsername(newUsername: string): Promise<User> {
  const updated = await api.updateUsername(newUsername);
  setUser(updated);
  return updated;
}

function refreshUser(): Promise<void> {
  return api.getMe().then(setUser);
}

export const authStore = {
  user,
  loading,
  signalrConnected,
  initialize,
  updateUsername,
  refreshUser,
};
