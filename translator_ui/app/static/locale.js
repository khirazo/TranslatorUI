export const localeKey = 'translator-ui.locale';
export const locales = {
  en: { name: 'English', asset: null },
  ja: { name: '日本語', asset: '/static/locales/ja.json' },
};

const english = {
  "subtitle": "Streaming text translation with LLMs",
  "settings": "Translation settings",
  "loadingProvider": "Loading provider",
  "loadingModel": "Loading model",
  "provider": "Provider",
  "model": "Model",
  "effort": "Effort",
  "unsupported": "Unavailable",
  "reloading": "Reloading…",
  "reload": "Reload settings",
  "profiles": "Saved profiles",
  "choose": "Select a profile",
  "profileName": "Profile name",
  "profileExample": "e.g. Qwen · EN to JA · plain",
  "save": "Save",
  "delete": "Delete",
  "dismiss": "Dismiss notification",
  "close": "Close",
  "source": "Source language",
  "swap": "Swap languages and text",
  "target": "Target language",
  "style": "Style",
  "polite": "Polite (desu/masu)",
  "plain": "Plain (da/de aru)",
  "copy": "Copy",
  "clear": "Clear",
  "input": "Enter text in {language}…",
  "translating": "Translating…",
  "translate": "Translate",
  "output": "Translation appears here",
  "stop": "Stop",
  "reloaded": "Settings reloaded.",
  "reset": "Settings changed. The selection was reset to its defaults.",
  "providersFailed": "Could not load translation settings.",
  "profilesFailed": "Could not load profiles.",
  "profileUnavailable": "This profile’s model is currently unavailable.",
  "saveFailed": "Could not save the profile. Reload settings and try again.",
  "deleteFailed": "Could not delete the profile. Reload settings and try again.",
  "copyFailed": "Could not copy. Check your browser’s clipboard permissions.",
  "reloadFailed": "Could not reload settings.",
  "translationFailed": "Translation failed: {message}",
  "displayLanguage": "Display language",
  "language.ja": "Japanese",
  "language.en": "English",
  "language.zh": "Simplified Chinese",
  "language.zh-tw": "Traditional Chinese",
  "language.ko": "Korean",
  "language.ar": "Arabic",
  "language.it": "Italian",
  "language.id": "Indonesian",
  "language.nl": "Dutch",
  "language.es": "Spanish",
  "language.th": "Thai",
  "language.de": "German",
  "language.fr": "French",
  "language.vi": "Vietnamese",
  "language.ru": "Russian"
};

export function resolveLocale() {
  const query = new URLSearchParams(window.location.search).get('locale');
  if (Object.hasOwn(locales, query)) return query;
  try {
    const saved = localStorage.getItem(localeKey);
    if (Object.hasOwn(locales, saved)) return saved;
  } catch {}
  for (const language of navigator.languages?.length ? navigator.languages : [navigator.language]) {
    const tag = language?.toLowerCase().split('-')[0];
    if (Object.hasOwn(locales, tag)) return tag;
  }
  return 'en';
}

export async function loadMessages(locale) {
  const asset = Object.hasOwn(locales, locale) && locales[locale].asset;
  if (!asset) return {};
  try {
    const response = await fetch(asset);
    if (!response.ok) return {};
    const messages = await response.json();
    return messages && typeof messages === 'object' ? messages : {};
  } catch {
    return {};
  }
}

export function translate(messages, key, params = {}) {
  const fallback = Object.hasOwn(english, key) ? english[key] : key;
  const message = Object.hasOwn(messages, key) && typeof messages[key] === 'string'
    ? messages[key]
    : fallback;
  return message.replace(/\{(\w+)\}/g, (placeholder, name) =>
    Object.hasOwn(params, name) ? params[name] : placeholder);
}
