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
    <div class="min-h-screen bg-linear-to-br from-purple-600 to-blue-500">
      {}
      <nav class="fixed top-0 left-0 right-0 z-50 bg-black/20 backdrop-blur-md border-b border-white/10">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div class="flex items-center justify-between h-16">
            {}
            <div class="shrink-0">
              <span class="text-xl font-bold text-white tracking-wider">RNGWars</span>
            </div>

            {}
            {}

            {}
            <div class="hidden md:flex items-center space-x-4">
              <a
                href={gameUrl}
                class="bg-white/20 hover:bg-white/30 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors duration-200 backdrop-blur-xs"
              >
                Play
              </a>
            </div>

            {}
            <div class="md:hidden">
              <button
                onClick={toggleMobileMenu}
                class="text-white/90 hover:text-white p-2 transition-colors duration-200"
                aria-label="Toggle mobile menu"
              >
                <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
          class={`md:hidden transition-all duration-300 ease-in-out ${
            isMobileMenuOpen() ? "max-h-96 opacity-100" : "max-h-0 opacity-0 overflow-hidden"
          }`}
        >
          <div class="px-4 pt-2 pb-4 space-y-2 bg-black/30 backdrop-blur-lg border-t border-white/10">
            <a
              href={gameUrl}
              class="block bg-white/20 hover:bg-white/30 text-white px-3 py-2 rounded-md text-base font-medium transition-colors duration-200 backdrop-blur-xs text-center"
            >
              Play
            </a>
          </div>
        </div>
      </nav>

      {}
      <div class="flex items-center justify-center min-h-screen pt-16">
        <h1 class="text-4xl font-bold text-white tracking-wider hover:scale-110 transition-transform duration-300">
          RNGWars
        </h1>
      </div>
    </div>
  );
};

export default Navigation;
