// exmap/src/server/mutex.ts — Mutex (promise chain; design §9). Step-zero stub.
export class Mutex {
  run<T>(fn: () => Promise<T> | T): Promise<T> {
    void fn;
    throw new Error("not implemented: Mutex.run");
  }
}
