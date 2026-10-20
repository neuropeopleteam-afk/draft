// Общие голосовые компоненты (интервью, голосовой ввод потребности): запись «нажми и говори», кнопка с распознаванием,
// проигрывание голоса с уровнем сигнала и собственная анимация собеседника. Описание API — docs/INTERVIEW.md, раздел «Голос».
export { REC_MESSAGES, rmsLevel, useSpeechPlayer, useVoiceRecorder, vadInit, vadStep, voiceSupported } from "./recorder";
export type { RecErrorCode, RecState, VadInfo, VadPhase, VadState, VoiceRecorder, VoiceRecorderOptions } from "./recorder";
export { VoiceAnswerButton, ListeningMeter } from "./VoiceAnswerButton";
export type { VoiceAnswerButtonProps } from "./VoiceAnswerButton";
export { VoiceRecordButton, postAudio } from "./VoiceRecordButton";
export type { Transcribed, VoiceRecordButtonProps } from "./VoiceRecordButton";
export { VoiceWave, WAVE_LABEL } from "./VoiceWave";
export type { VoiceWaveProps, WaveState } from "./VoiceWave";
export { InterviewerAvatar } from "./InterviewerAvatar";
export type { InterviewerAvatarProps } from "./InterviewerAvatar";
export { AnamAvatar } from "./AnamAvatar";
export type { AnamAvatarProps, AnamHandle, AnamStatus, AnamWriter } from "./AnamAvatar";
// Живой разговор «как по видеосвязи»: микрофон один раз, потоковое распознавание, голос в поток аватара с запасным выводом
export { LiveListener, liveSttSupported } from "./live/listener";
export type { MicState, SttEvent } from "./live/listener";
export { SpeechBuffer, bargeIn, endDelay, isBackchannel, isEcho, stripEndMarker, words } from "./live/turns";
export { Voice } from "./live/voice";
export type { SayResult, Utterance } from "./live/voice";
export { PcmPlayer } from "./live/player";
export { dictationSupported, pickRuVoice, ttsSupported, useBrowserTts, useLiveDictation } from "./browserSpeech";
export type { DictationOptions } from "./browserSpeech";
