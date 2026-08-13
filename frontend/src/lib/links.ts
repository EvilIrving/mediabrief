/** Public site. Check for updates opens the landing page; privacy is its own page. */
export const DOWNLOAD_PAGE_URL = "https://evilirving.github.io/mediabrief/"
export const PRIVACY_PAGE_URL = "https://evilirving.github.io/mediabrief/privacy.html"

const ALLOWED_PREFIXES = [
  "https://evilirving.github.io/mediabrief",
  "https://github.com/EvilIrving/mediabrief",
]

function isAllowedExternalUrl(url: string): boolean {
  return ALLOWED_PREFIXES.some((prefix) => url === prefix || url.startsWith(`${prefix}/`) || url.startsWith(`${prefix}#`) || url.startsWith(`${prefix}?`))
}

type DesktopBridge = {
  pywebview?: { api?: { open_url?: (url: string) => Promise<boolean> | boolean } }
}

export function openExternal(url: string): void {
  if (!isAllowedExternalUrl(url)) return
  const bridge = window as Window & DesktopBridge
  const openUrl = bridge.pywebview?.api?.open_url
  if (typeof openUrl === "function") {
    void openUrl(url)
    return
  }
  window.open(url, "_blank", "noopener,noreferrer")
}

export function isAllowedDownloadUrl(url: string): boolean {
  return isAllowedExternalUrl(url)
}
