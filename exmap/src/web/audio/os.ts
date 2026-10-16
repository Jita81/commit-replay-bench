// exmap/src/web/audio/os.ts — OS and browser detection for the guidance pages (design §7.2).
import type { OsId } from "./types.js";

export interface NavigatorLike {
  userAgent?: string;
  userAgentData?: { platform?: string; brands?: Array<{ brand: string; version: string }> } | undefined;
  platform?: string;
}

function fromPlatform(platform: string): OsId | null {
  const p = platform.toLowerCase();
  if (p.startsWith("win")) return "windows";
  if (p.startsWith("mac")) return "macos";
  if (p.includes("linux") || p.includes("x11") || p.includes("ubuntu") || p.includes("cros")) return "linux";
  return null;
}

/** `navigator.userAgentData.platform` first, then user-agent regexes. */
export function detectOs(nav: NavigatorLike | undefined = typeof navigator === "undefined" ? undefined : (navigator as NavigatorLike)): OsId {
  if (!nav) return "other";
  const uaPlatform = nav.userAgentData?.platform;
  if (typeof uaPlatform === "string" && uaPlatform.length > 0) {
    const os = fromPlatform(uaPlatform);
    if (os) return os;
  }
  const ua = nav.userAgent ?? "";
  if (/Windows NT|Win64|Win32/i.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/i.test(ua) && !/like Mac OS X/i.test(ua)) return "macos";
  if (/X11|Linux|Ubuntu|CrOS/i.test(ua) && !/Android/i.test(ua)) return "linux";
  if (typeof nav.platform === "string" && nav.platform) {
    const os = fromPlatform(nav.platform);
    if (os) return os;
  }
  return "other";
}

/** Chromium-based browsers (Chrome, Edge, Brave, Opera…) are the only ones that can share tab/system audio. */
export function isChromium(nav: NavigatorLike | undefined = typeof navigator === "undefined" ? undefined : (navigator as NavigatorLike)): boolean {
  if (!nav) return false;
  const brands = nav.userAgentData?.brands;
  if (Array.isArray(brands) && brands.length > 0) {
    return brands.some((b) => /Chromium|Google Chrome|Microsoft Edge/i.test(b.brand));
  }
  const ua = nav.userAgent ?? "";
  if (/Firefox\//i.test(ua)) return false;
  if (/Edg\//i.test(ua) || /Chrome\//i.test(ua) || /Chromium\//i.test(ua)) return true;
  return false;
}

export const OS_LABEL: Record<OsId, string> = { windows: "Windows", macos: "macOS", linux: "Linux", other: "this OS" };
