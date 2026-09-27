import { defineStore } from 'pinia'
import { api } from '@/api'
import { initLocale } from '@/i18n'

export const useSessionStore = defineStore('session', {
  state: () => ({
    loaded: false,
    pyfaVersion: '',
    language: 'en_US',
    gamedata: { build: '', date: '' },
    sso: { server: '', configured: false, devBypass: false },
    user: null as { characterName: string; characterId: number } | null,
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

    async logout() {
      await api.logout()
      window.location.href = '/'
    },
  },
})
