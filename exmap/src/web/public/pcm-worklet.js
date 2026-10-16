// exmap/src/web/public/pcm-worklet.js — served at /pcm-worklet.js (design §7.3). Plain ES2022, no imports (the worklet
// globals are not in TS 5.9's libs). Frames the first input channel into FRAME = round(sampleRate × 0.02) samples
// (320 at 16 kHz) and posts { type: "frame", pcm } with the buffer transferred. On { type: "flush" } it posts the
// zero-padded partial frame (if any) and then { type: "flushed" }. process() always returns true so the node stays
// alive; zero-channel input posts nothing. The node has channelCount 1 / explicit, so stereo is down-mixed before here.
class ExmapPcmFramer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frameSize = Math.round(sampleRate * 0.02);
    this.buffer = new Float32Array(this.frameSize);
    this.fill = 0;
    this.port.onmessage = (ev) => {
      const data = ev.data;
      if (data && data.type === "flush") {
        if (this.fill > 0) {
          this.buffer.fill(0, this.fill);
          this.emit();
        }
        this.port.postMessage({ type: "flushed" });
      }
    };
  }

  emit() {
    const pcm = this.buffer;
    this.buffer = new Float32Array(this.frameSize);
    this.fill = 0;
    this.port.postMessage({ type: "frame", pcm }, [pcm.buffer]);
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel || channel.length === 0) return true;
    let offset = 0;
    while (offset < channel.length) {
      const room = this.frameSize - this.fill;
      const take = Math.min(room, channel.length - offset);
      this.buffer.set(channel.subarray(offset, offset + take), this.fill);
      this.fill += take;
      offset += take;
      if (this.fill === this.frameSize) this.emit();
    }
    return true;
  }
}

registerProcessor("exmap-pcm-framer", ExmapPcmFramer);
