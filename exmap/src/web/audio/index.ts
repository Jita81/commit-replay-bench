// exmap/src/web/audio/index.ts — the audio module's public surface (design §7). The web module imports from here.
export type * from "./types.js";
export { LANE_ERROR, LANE_ERROR_TEXT, PROVIDER_ERROR, LaneStateError, GraphError, ProviderError, PostError, mapDomException, isProviderError } from "./errors.js";
export { detectOs, isChromium, OS_LABEL } from "./os.js";
export { createSessionClock, fixedClock } from "./clock.js";
export {
  SETTINGS_KEY, MODEL_SEEN_KEY, WEBSPEECH_SEEN_KEY, WHISPER_MODELS, WHISPER_DTYPES, MODEL_INFO, modelShortName, defaultSettings, normalizeSettings, loadSettings, saveSettings,
  readFlag, writeFlag, memoryStorage, browserStorage,
} from "./settings.js";
export { SpeakerStore, SPEAKER_COPY, REMOTE_KNOWN_KEY, ME_LABEL_KEY, REMOTE_KNOWN_MAX, type SpeakerStoreDeps } from "./speakers.js";
export { AudioController, audioTestHooks, fetchReplayIndex, fetchReplayFixture, type AudioControllerDeps, type ReplayIndexEntry } from "./controller.js";

export { CaptureLane, guidanceReasonFor, SILENT_AFTER_MS, SILENT_BELOW_DB, type CaptureLaneDeps, type CaptureLaneHooks } from "./lanes/captureLane.js";
export { REMOTE_DISPLAY_OPTIONS, deviceConstraints, type DisplayMediaOptionsEx } from "./lanes/constraints.js";
export { listAudioInputs, primeDeviceLabels, onDeviceChange, isDefault, labelsAvailable, type AudioInputInfo } from "./lanes/devices.js";
export { guidanceFor, GUIDANCE_REASONS, GUIDANCE_OSES, type Guidance } from "./lanes/guidance.js";

export { WebAudioGraph, WORKLET_URL, WORKLET_NAME, type AudioGraph, type GraphDeps, type AudioContextLike, type WorkletNodeLike, type SourceNodeLike, type FrameHandler } from "./dsp/graph.js";
export { DEFAULT_VAD, FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE, createVadState, vadStep, frameRms, rmsToDb, speechThresholdDb, type VadConfig, type VadState, type VadStep } from "./dsp/vad.js";
export { DEFAULT_SEGMENTER, createSegmenter, segmenterStep, segmenterFlush, type SegmenterConfig, type SegmenterState, type SegmenterStepResult } from "./dsp/segmenter.js";
export { levelStep } from "./dsp/levels.js";
export { resampleTo16k, TARGET_RATE } from "./dsp/resample.js";

export { PROVIDERS, createProvider, providerLabelFor, type ProviderInfo, type ProviderDeps } from "./providers/registry.js";
export { LocalWhisperProvider, ORT_WASM_PATHS, DEFAULT_LOAD_TIMEOUT_MS, whisperThreads, defaultCreateWorker, type LocalWhisperDeps, type WorkerLike } from "./providers/localWhisper.js";
export { ManualProvider } from "./providers/manual.js";
export { ReplayProvider, parseReplayFixture, estimateDurationMs, REPLAY_SPEEDS, type ReplayTimers } from "./providers/replay.js";
export {
  WebSpeechProvider, speechRecognitionCtor, WEB_SPEECH_LABEL, WEB_SPEECH_NOTICE,
  type SpeechRecognitionCtor, type SpeechRecognitionLike, type SpeechRecognitionEventLike, type SpeechRecognitionErrorEventLike, type WebSpeechDeps,
} from "./providers/webSpeech.js";
export { isLikelyHallucination, normalizeTranscript, KNOWN_HALLUCINATIONS } from "./providers/hallucination.js";

export { buildUtterance, mintUtteranceId } from "./pipeline/utteranceBuilder.js";
export { HttpUtteranceSink, MemorySink, classifyResponse, DEFAULT_POST_TIMEOUT_MS, type FetchLike, type HttpSinkOptions } from "./pipeline/sink.js";
export { PostQueue, POST_BACKOFF_MS, DEFAULT_MAX_IN_FLIGHT, type PostQueueOptions, type PostQueueEvents } from "./pipeline/postQueue.js";
export { TranscriptionQueue, type TranscriptionQueueDeps } from "./pipeline/transcriptionQueue.js";

export { useAudioController } from "./react/useAudioController.js";
export { CaptureControls, backlogText, type CaptureControlsProps } from "./react/CaptureControls.jsx";
export { LaneBadge, ProviderBadge, laneStateText, LANE_NAME } from "./react/LaneBadge.jsx";
export { LevelMeter } from "./react/LevelMeter.jsx";
export { DevicePicker } from "./react/DevicePicker.jsx";
export { SpeakerPicker } from "./react/SpeakerPicker.jsx";
export { ModelProgress, modelProgressText } from "./react/ModelProgress.jsx";
export { ConsentNotice, modelNoticeText, type ConsentNoticeProps, type ConsentController } from "./react/ConsentNotice.jsx";
export { GuidancePanel, GuidancePanelView, type GuidancePanelProps } from "./react/GuidancePanel.jsx";
export { ManualInput, type ManualInputProps } from "./react/ManualInput.jsx";
export { ReplayControls, type ReplayControlsProps } from "./react/ReplayControls.jsx";
