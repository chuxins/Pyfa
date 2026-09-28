import { defineStore } from 'pinia'
import { api } from '@/api'
import { initLocale } from '@/i18n'

/**
 * Why the sign-in prompt is on screen: `import` names the EVE fittings import, which is
 * the one action that asks for a login before it tries, `any` is every other write the
 * server answered 401 to.
 */
export type LoginReason = 'import' | 'any'

export const useSessionStore = defineStore('session', {
  state: () => ({
    loaded: false,
    pyfaVersion: '',
    language: 'en_US',
    gamedata: { build: '', date: '' },
    sso: { server: '', configured: false, devBypass: false },
    user: null as { characterName: string; characterId: number } | null,
    /** What the sign-in prompt on screen is about, or '' when it is not up */
    loginPrompt: '' as '' | LoginReason,
  }),

  getters: {
    signedIn: (state) => state.user !== null,
  },

  actions: {
    async load() {
      const meta = await api.meta()
      this.pyfaVersion = meta.pyfaVersion
      this.language = meta.language
      // The server's language is the default for the UI chrome as well as for the
      // item names it sends; an explicit choice in the picker still wins.
      initLocale(meta.language)
      this.gamedata = meta.gamedata
      this.sso = meta.sso
      this.user = meta.user
      this.loaded = true
    },

    /** Ask for a login before the action that needs one, or after the server refused it. */
    promptLogin(reason: LoginReason = 'any') {
      this.loginPrompt = reason
    },

    dismissLoginPrompt() {
      this.loginPrompt = ''
    },

    async logout() {
      await api.logout()
      window.location.href = '/'
    },
  },
})
