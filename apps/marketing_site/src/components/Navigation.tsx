import type { Component } from "solid-js";
import { createSignal } from "solid-js";

interface NavigationProps {
  gameUrl?: string;
}

const Navigation: Component<NavigationProps> = (props) => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = createSignal(false);

  const toggleMobileMenu = () => {
    setIsMobileMenuOpen(!isMobileMenuOpen());
  };

  const gameUrl = props.gameUrl || "http://localhost:4000";

  return (
    <div class="landing">
      {}
      <nav class="site-header">
        <div class="site-header-inner">
          <div class="site-header-bar">
            {}
            <div class="site-brand">
              <span class="site-wordmark">RNGWars</span>
            </div>

            {}
            {}

            {}
            <div class="desktop-nav">
              <a href={gameUrl} class="play-link">
                Play
              </a>
            </div>

            {}
            <div class="menu-toggle-wrap">
              <button
                onClick={toggleMobileMenu}
                class="menu-toggle"
                aria-label="Toggle mobile menu"
              >
                <svg class="menu-toggle-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d={isMobileMenuOpen() ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"}
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>

        {}
        <div
          class={
            isMobileMenuOpen() ? "mobile-menu mobile-menu-open" : "mobile-menu mobile-menu-closed"
          }
        >
          <div class="mobile-menu-panel">
            <a href={gameUrl} class="play-link play-link-mobile">
              Play
            </a>
          </div>
        </div>
      </nav>

      {}
      <div class="hero">
        <h1 class="hero-title">RNGWars</h1>
      </div>
    </div>
  );
};

export default Navigation;
