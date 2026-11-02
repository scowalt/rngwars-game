import type { ParentComponent } from "solid-js";
import { A } from "@solidjs/router";
import { authStore } from "../stores/authStore";

const Layout: ParentComponent = (props) => {
  return (
    <div class="min-h-screen flex flex-col">
      <nav class="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <A href="/" class="text-xl font-bold text-brand">
          RNGWars
        </A>
        <div class="flex items-center gap-4">
          <A href="/leaderboard" class="text-gray-400 hover:text-white transition-colors">
            Leaderboard
          </A>
          <A href="/history" class="text-gray-400 hover:text-white transition-colors">
            History
          </A>
          <div class="text-sm text-gray-400">{authStore.user()?.username ?? "..."}</div>
        </div>
      </nav>
      <main class="flex-1 flex flex-col">{props.children}</main>
    </div>
  );
};

export default Layout;
