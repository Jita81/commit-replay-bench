// Anti-FOUC: resolve the stored theme before first paint. "system" leaves
// data-theme unset so prefers-color-scheme decides (see src/lib/theme.ts).
// Served as a file (not inline) so the API's CSP `default-src 'self'` allows it.
(function () {
  try {
    var t = localStorage.getItem('crb.theme');
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
  } catch (e) {}
})();
