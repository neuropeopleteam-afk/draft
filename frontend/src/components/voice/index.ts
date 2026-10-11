// Общие голосовые компоненты (интервью, голосовой ввод потребности): запись «нажми и говори», кнопка с распознаванием,
// проигрывание голоса с уровнем сигнала и собственная анимация собеседника. Описание API — docs/INTERVIEW.md, раздел «Голос».
export { REC_MESSAGES, rmsLevel, useSpeechPlayer, useVoiceRecorder, voiceSupported } from "./recorder";
export type { RecErrorCode, RecState, VoiceRecorder, VoiceRecorderOptions } from "./recorder";
export { VoiceRecordButton, postAudio } from "./VoiceRecordButton";
export type { Transcribed, VoiceRecordButtonProps } from "./VoiceRecordButton";
export { VoiceWave, WAVE_LABEL } from "./VoiceWave";
export type { VoiceWaveProps, WaveState } from "./VoiceWave";
export { InterviewerAvatar } from "./InterviewerAvatar";
export type { InterviewerAvatarProps } from "./InterviewerAvatar";
export { AnamAvatar } from "./AnamAvatar";
export type { AnamAvatarProps, AnamHandle, AnamStatus } from "./AnamAvatar";
