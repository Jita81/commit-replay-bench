// exmap/src/web/public/pcm-worklet.js — served at /pcm-worklet.js (design §7.3). Plain ES2022, no imports (the worklet
// globals are not in TS 5.9's libs). Step-zero stub: registers the processor name the graph loads; the audio module
// adds the 20 ms framing ({ type: "frame", pcm }), the flush protocol and the zero-channel guard.
class ExmapPcmFramer extends AudioWorkletProcessor {
  process() {
    return true;
  }
}
registerProcessor("exmap-pcm-framer", ExmapPcmFramer);
