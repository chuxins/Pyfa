<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { onUnauthorized } from '@/api'
import { useSessionStore } from '@/stores/session'
import { useBrowserStore } from '@/stores/browser'
import { useFittingStore } from '@/stores/fitting'
import { ssoErrorText } from '@/errors'
import { LOCALES, locale, setLocale, t, type LocaleCode } from '@/i18n'
import ShipBrowser from '@/components/ShipBrowser.vue'
import FittingView from '@/components/FittingView.vue'
import LoginPrompt from '@/components/LoginPrompt.vue'
import StatsPane from '@/components/StatsPane.vue'
import ItemBrowser from '@/components/ItemBrowser.vue'
import ItemDetails from '@/components/ItemDetails.vue'

const session = useSessionStore()
const browser = useBrowserStore()
const fitting = useFittingStore()

const itemPaneOpen = ref(true)
const detailsOpen = ref(false)

/** How long a refused login stays on screen before it gets out of the way again. */
const SSO_ERROR_TIMEOUT = 8000

/** Set from `?sso_error=` when EVE sent the browser back with a refusal. */
const ssoError = ref<string | null>(null)
let ssoErrorTimer: number | undefined

/** Where the sign-in link sends the browser back to, so the page is not lost. */
const signInHref = computed(() => {
  const here = window.location.pathname + window.location.search
  return '/api/auth/login?next=' + encodeURIComponent(here || '/')
})

/** Read a refusal out of the address bar and drop it, so a reload is a clean start. */
function takeSsoError(): string | null {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('sso_error')
  if (!code) return null
  params.delete('sso_error')
  const query = params.toString()
  window.history.replaceState({}, '', window.location.pathname + (query ? `?${query}` : ''))
  return ssoErrorText(code)
}

onMounted(async () => {
  // A write the server turns down for want of a session raises the sign-in prompt instead
  // of a banner the click cannot act on (see @/api, @/components/LoginPrompt.vue)
  onUnauthorized(() => session.promptLogin())

  ssoError.value = takeSsoError()
  if (ssoError.value) {
    ssoErrorTimer = window.setTimeout(() => (ssoError.value = null), SSO_ERROR_TIMEOUT)
  }

  await session.load()
  // The tree is readable without a session -- the server falls back to guest game data --
  // so the ship list, the item browser and the stats panes are there from the start. The
  // fits themselves and the live stream are what a session adds.
  await browser.loadTree()
  if (session.signedIn) {
    fitting.connect()
    // Land on the fit last worked on: the assembly page is the view to come up on, rather
    // than an empty frame between the browser and the stats.
    await fitting.openLast()
  }
})

onUnmounted(() => {
  fitting.disconnect()
  if (ssoErrorTimer) window.clearTimeout(ssoErrorTimer)
})

const showDetails = computed(() => browser.selectedItem !== null)

/** One line for whatever went wrong or just happened, whichever store said it. */
const bannerError = computed(() => fitting.error || browser.error)
const bannerNotice = computed(() => fitting.notice || browser.notice || ssoError.value)

/** The picker writes the choice to localStorage, so it outlives the page. */
function changeLocale(event: Event) {
  setLocale((event.target as HTMLSelectElement).value as LocaleCode)
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <strong>pyfa</strong><span class="dim">web</span>
      </div>

      <div v-if="fitting.fit" class="fitbar">
        <span class="shipname">{{ fitting.fit.ship.item.name }}</span>
        <input
          class="fitname"
          :value="fitting.fit.name"
          @change="fitting.rename(($event.target as HTMLInputElement).value)"
        />
        <button :disabled="!fitting.history.canUndo || fitting.busy" :title="fitting.history.undoName ?? 'Undo'" @click="fitting.undo()">
          &#8630; {{ t('Undo') }}
        </button>
        <button :disabled="!fitting.history.canRedo || fitting.busy" :title="fitting.history.redoName ?? 'Redo'" @click="fitting.redo()">
          &#8631; {{ t('Redo') }}
        </button>
        <button :disabled="fitting.busy" @click="fitting.reset()">{{ t('Clear fit') }}</button>
        <span v-if="fitting.busy" class="dim">{{ t('working…') }}</span>
      </div>

      <div class="spacer" />

      <button @click="itemPaneOpen = !itemPaneOpen">
        {{ t(itemPaneOpen ? 'Hide item browser' : 'Show item browser') }}
      </button>
      <select class="lang" :value="locale" :title="t('Interface language')" @change="changeLocale">
        <option v-for="entry in LOCALES" :key="entry.code" :value="entry.code">{{ entry.label }}</option>
      </select>
      <span v-if="session.signedIn" class="user">
        {{ session.user?.characterName }}
        <button @click="session.logout()">{{ t('Sign out') }}</button>
      </span>
      <a v-else class="signin" :href="signInHref">{{ t('Sign in with EVE') }}</a>
      <span
        class="dim version"
        :title="t('gamedata build {build}', { build: session.gamedata.build })"
      >v{{ session.pyfaVersion }}</span>
    </header>

    <div v-if="bannerError" class="banner error">{{ bannerError }}</div>
    <div v-else-if="bannerNotice" class="banner notice">{{ bannerNotice }}</div>

    <main class="body">
      <ShipBrowser class="sidebar" />

      <section class="center">
        <FittingView v-if="fitting.fit" />
        <div v-else class="placeholder">
          <!-- Signed out the page is still the whole application: it is the writes that
               need an account, and the click that asks for one raises the sign-in dialog -->
          <template v-if="session.signedIn">
            <h2>{{ t('No fit open') }}</h2>
            <p class="dim">{{ t('Pick a ship on the left, then open one of its fits or create a new one.') }}</p>
          </template>
          <template v-else>
            <h2>{{ t('Sign in to build fits') }}</h2>
            <p class="dim">
              {{ t('Browsing ships and items works signed out; saving a fit needs an EVE login.') }}
            </p>
            <p class="dim">{{ t('EVE SSO is how pyfa web knows whose fits to load.') }}</p>
            <a :href="signInHref"><button class="primary">{{ t('Sign in with EVE') }}</button></a>
            <p v-if="!session.sso.configured" class="dim hint">
              {{ t('EVE SSO is not configured on this server.') }}
              {{ t('Set PYFA_WEB_SSO_CLIENT_ID, or run the server with --dev-login for development.') }}
            </p>
          </template>
        </div>
      </section>

      <aside class="right">
        <ItemDetails v-if="showDetails" @close="browser.clearItem()" />
        <StatsPane v-else />
      </aside>
    </main>

    <ItemBrowser v-if="itemPaneOpen" class="itembar" />

    <LoginPrompt v-if="session.loginPrompt" @close="session.dismissLoginPrompt()" />
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  height: 100%;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
}

.brand {
  font-size: 15px;
  letter-spacing: 0.02em;
  margin-right: 8px;
}

.brand span {
  margin-left: 4px;
}

.fitbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.shipname {
  font-weight: 600;
}

.fitname {
  width: 190px;
}

.spacer {
  flex: 1;
}

.user {
  display: flex;
  align-items: center;
  gap: 8px;
}

.version {
  font-size: 11px;
}

.lang {
  font-size: 11px;
  padding: 1px 4px;
}

.banner {
  padding: 6px 12px;
  font-size: 12px;
}

.banner.error {
  background: var(--danger);
  color: #fff;
}

.banner.notice {
  background: var(--accent-dim);
}

.body {
  display: grid;
  grid-template-columns: 280px minmax(420px, 1fr) 340px;
  min-height: 0;
}

.sidebar {
  border-right: 1px solid var(--border);
  background: var(--bg-panel);
  min-height: 0;
}

.center {
  min-height: 0;
  overflow: auto;
}

.right {
  border-left: 1px solid var(--border);
  background: var(--bg-panel);
  min-height: 0;
  overflow: auto;
}

.itembar {
  border-top: 1px solid var(--border);
  background: var(--bg-panel);
  height: 240px;
}

.placeholder {
  padding: 40px;
  text-align: center;
}

.placeholder h2 {
  margin: 0 0 6px;
  font-weight: 600;
}

.hint {
  margin-top: 14px;
  max-width: 32rem;
  margin-left: auto;
  margin-right: auto;
}
</style>
