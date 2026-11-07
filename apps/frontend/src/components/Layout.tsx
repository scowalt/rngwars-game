import type { ParentComponent } from "solid-js";
import { A } from "@solidjs/router";
import { authStore } from "../stores/authStore";

const Layout: ParentComponent = (props) => {
  return (
    <div class="app-shell">
      <nav class="site-header">
        <A href="/" class="site-logo">
          RNGWars
        </A>
        <div class="site-nav">
          <A href="/leaderboard" class="site-nav-link">
            Leaderboard
          </A>
          <A href="/history" class="site-nav-link">
            History
          </A>
          <div class="site-user">{authStore.user()?.username ?? "..."}</div>
        </div>
      </nav>
      <main class="app-main">{props.children}</main>
    </div>
  );
};

export default Layout;
