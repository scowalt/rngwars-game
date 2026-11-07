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
          <button onClick={startEditing} class="username-button">
            {authStore.user()?.username ?? "..."} <span class="username-edit-hint">edit</span>
          </button>
        }
      >
        <div class="username-form">
          <input
            type="text"
            value={value()}
            onInput={(e) => setValue(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              if (e.key === "Escape") cancel();
            }}
            maxLength={20}
            class="username-input"
            autofocus
          />
          <button onClick={save} disabled={saving()} class="editor-button editor-button-save">
            {saving() ? "..." : "Save"}
          </button>
          <button onClick={cancel} class="editor-button editor-button-cancel">
            Cancel
          </button>
        </div>
        <Show when={error()}>
          <p class="username-error">{error()}</p>
        </Show>
      </Show>
    </div>
  );
};

export default UsernameEditor;
