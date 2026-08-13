import { describe, expect, it } from "vitest"
import { DOWNLOAD_PAGE_URL, PRIVACY_PAGE_URL, isAllowedDownloadUrl } from "./links"

describe("download page links", () => {
  it("points check-for-updates at the public download page", () => {
    expect(DOWNLOAD_PAGE_URL).toBe("https://evilirving.github.io/mediabrief/")
    expect(PRIVACY_PAGE_URL).toBe("https://evilirving.github.io/mediabrief/#privacy")
  })

  it("only allows MediaBrief download and GitHub URLs", () => {
    expect(isAllowedDownloadUrl(DOWNLOAD_PAGE_URL)).toBe(true)
    expect(isAllowedDownloadUrl(PRIVACY_PAGE_URL)).toBe(true)
    expect(isAllowedDownloadUrl("https://github.com/EvilIrving/mediabrief/releases/latest")).toBe(true)
    expect(isAllowedDownloadUrl("https://example.com")).toBe(false)
  })
})
