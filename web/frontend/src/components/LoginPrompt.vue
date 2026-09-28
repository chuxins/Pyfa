<script setup lang="ts">
/**
 * The sign-in prompt: what a click that needs an account gets instead of a dead end.
 *
 * The page itself is readable signed out -- ships, items and their numbers come from the
 * guest game data -- so the sign-in is not a wall across the screen but a dialog raised by
 * the click that needs the account (see `@/api` and `@/stores/browser`). The session cookie
 * is what EVE's answer comes back on, so the button is a link to the server's login route,
 * with the page the click was on in `next`.
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { useSessionStore } from '@/stores/session'
import { t } from '@/i18n'

const session = useSessionStore()

const emit = defineEmits<{ close: [] }>()

/** Where EVE sends the browser back to, so the page the click was on is not lost. */
const signInHref = computed(() => {
  const here = window.location.pathname + window.location.search
  return '/api/auth/login?next=' + encodeURIComponent(here || '/')
})

/** One sentence about the click that asked: importing and saving read differently. */
const reason = computed(() =>
  session.loginPrompt === 'import'
    ? t('Importing your EVE fits reads them from EVE as you, so it needs a login first.')
    : t('Saving a change to a fit needs a login, so the server knows whose fit it is.'),
)

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="dialog" role="dialog" aria-modal="true">
      <h2>{{ t('Sign in to continue') }}</h2>
      <p class="dim">{{ reason }}</p>
      <div class="buttons">
        <a :href="signInHref"><button class="primary">{{ t('Sign in with EVE') }}</button></a>
        <button @click="emit('close')">{{ t('Cancel') }}</button>
      </div>
      <p v-if="!session.sso.configured" class="dim hint">
        {{ t('EVE SSO is not configured on this server.') }}
        {{ t('Set PYFA_WEB_SSO_CLIENT_ID, or run the server with --dev-login for development.') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
}

.dialog {
  width: min(24rem, calc(100vw - 2rem));
  padding: 16px 18px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
}

.dialog h2 {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 600;
}

.dialog p {
  margin: 0 0 14px;
}

.buttons {
  display: flex;
  gap: 8px;
  align-items: center;
}

.hint {
  font-size: 12px;
  margin: 12px 0 0;
}
</style>
