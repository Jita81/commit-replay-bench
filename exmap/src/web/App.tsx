// exmap/src/web/App.tsx — one screen, no router (design §10.1). Step zero renders a placeholder heading only;
// the web module replaces this with SessionPicker / the session screen.
export function App() {
  return (
    <main className="min-h-screen p-6 font-sans">
      <h1 className="text-2xl font-semibold">Example Map Live</h1>
      <p className="mt-2 text-sm opacity-70">A local-first, voice-driven requirements modeller with human verification.</p>
    </main>
  );
}

export default App;
