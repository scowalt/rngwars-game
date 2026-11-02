import { Component, createSignal, Show } from "solid-js";
import { authStore } from "../stores/authStore";

const UsernameEditor: Component = () => {
  const [editing, setEditing] = createSignal(false);
  const [value, setValue] = createSignal("");
  const [error, setError] = createSignal<string | null>(null);
  const [saving, setSaving] = createSignal(false);

  function startEditing() {
    setValue(authStore.user()?.username ?? "");
    setError(null);
    setEditing(true);
  }

  async function save() {
    const username = value().trim();
    if (username.length < 3 || username.length > 20) {
      setError("Username must be 3-20 characters");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await authStore.updateUsername(username);
      setEditing(false);
    } catch (e: unknown) {
      const apiError = e as { error?: { message?: string } };
      setError(apiError?.error?.message ?? "Failed to update username");
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setEditing(false);
    setError(null);
  }

  return (
    <div>
      <Show
        when={editing()}
        fallback={
          <button
            onClick={startEditing}
            class="text-lg font-semibold hover:text-brand transition-colors cursor-pointer"
          >
            {authStore.user()?.username ?? "..."} <span class="text-gray-500 text-sm">edit</span>
          </button>
        }
      >
        <div class="flex items-center gap-2">
          <input
            type="text"
            value={value()}
            onInput={(e) => setValue(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              if (e.key === "Escape") cancel();
            }}
            maxLength={20}
            class="bg-gray-800 border border-gray-600 rounded px-3 py-1 text-white focus:border-brand focus:outline-none"
            autofocus
          />
          <button
            onClick={save}
            disabled={saving()}
            class="px-3 py-1 bg-brand rounded text-white text-sm hover:bg-brand-light disabled:opacity-50"
          >
            {saving() ? "..." : "Save"}
          </button>
          <button
            onClick={cancel}
            class="px-3 py-1 bg-gray-700 rounded text-white text-sm hover:bg-gray-600"
          >
            Cancel
          </button>
        </div>
        <Show when={error()}>
          <p class="text-red-400 text-sm mt-1">{error()}</p>
        </Show>
      </Show>
    </div>
  );
};

export default UsernameEditor;
