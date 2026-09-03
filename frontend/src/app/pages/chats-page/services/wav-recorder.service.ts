import { Injectable, signal } from '@angular/core';
import { WavRecorder } from 'wavtools';
import { AudioAnalysisOutputType } from 'wavtools/dist/lib/analysis/audio_analysis';

export const SELECTED_MICROPHONE_STORAGE_KEY = 'selected_microphone_id';

@Injectable({
    providedIn: 'root',
})
export class WavRecorderService {
    private wavRecorder: WavRecorder;
    private deviceListenerAttached = false;
    private devicesReadyPromise: Promise<MediaDeviceInfo[]> | null = null;

    public audioDevices = signal<MediaDeviceInfo[]>([]);
    public isRecording = signal<boolean>(false);
    public isPaused = signal<boolean>(false);
    public isInitialized = signal<boolean>(false);
    public isLoadingDevices = signal<boolean>(false);
    /** Last ensureDevicesReady failed because the browser blocked the mic. */
    public permissionBlocked = signal<boolean>(false);

    constructor() {
        const isFirefox = navigator.userAgent.includes('Firefox');
        let sampleRate = 24000;
        if (isFirefox) {
            const probeCtx = new AudioContext();
            sampleRate = probeCtx.sampleRate;
            void probeCtx.close();
        }

        this.wavRecorder = new WavRecorder({ sampleRate });
        // Intentionally no device/permission work here — only on user gesture.
    }

    /**
     * Request mic + load devices. Must run from a click/tap.
     * Safe to call repeatedly (retries after failure).
     */
    public ensureDevicesReady(): Promise<MediaDeviceInfo[]> {
        const existing = this.audioDevices().filter((d) => d.deviceId);
        if (existing.length > 0) {
            return Promise.resolve(existing);
        }

        if (this.devicesReadyPromise) {
            return this.devicesReadyPromise;
        }

        this.isLoadingDevices.set(true);
        this.permissionBlocked.set(false);

        this.devicesReadyPromise = this.loadDevicesFromUserGesture().finally(() => {
            this.isLoadingDevices.set(false);
            this.devicesReadyPromise = null;
        });

        return this.devicesReadyPromise;
    }

    private async loadDevicesFromUserGesture(): Promise<MediaDeviceInfo[]> {
        if (!navigator.mediaDevices?.getUserMedia || !navigator.mediaDevices.enumerateDevices) {
            this.isInitialized.set(true);
            this.audioDevices.set([]);
            return [];
        }

        let stream: MediaStream | null = null;
        try {
            // Always open a stream in this call (user gesture). Even when the site
            // already has permission, Chrome often needs this before deviceIds appear.
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const devices = await navigator.mediaDevices.enumerateDevices();
            const audioInputs = devices.filter((d) => d.kind === 'audioinput');

            this.audioDevices.set(audioInputs);
            this.isInitialized.set(true);
            this.permissionBlocked.set(false);
            this.attachDeviceListener();
            return audioInputs;
        } catch (error) {
            console.error('Failed to access microphone / list devices:', error);
            const blocked =
                error instanceof DOMException &&
                (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError');
            this.permissionBlocked.set(blocked);
            this.isInitialized.set(true);
            this.audioDevices.set([]);
            return [];
        } finally {
            stream?.getTracks().forEach((track) => track.stop());
        }
    }

    private attachDeviceListener(): void {
        if (this.deviceListenerAttached || !navigator.mediaDevices) return;
        this.deviceListenerAttached = true;

        navigator.mediaDevices.addEventListener('devicechange', () => {
            void navigator.mediaDevices.enumerateDevices().then((devices) => {
                const audioInputs = devices.filter((d) => d.kind === 'audioinput');
                if (audioInputs.length > 0) {
                    this.audioDevices.set(audioInputs);
                }
            });
        });
    }

    public async beginRecording(deviceId?: string): Promise<boolean> {
        const isFirefox = navigator.userAgent.includes('Firefox');
        if (isFirefox) {
            window.alert(
                '⚠️ Voice capture on Firefox can be unreliable—OpenAI’s voice recognition may perform poorly here.'
            );
        }

        const resolvedDeviceId = deviceId ?? localStorage.getItem(SELECTED_MICROPHONE_STORAGE_KEY) ?? undefined;

        try {
            const success = await this.wavRecorder.begin(resolvedDeviceId);
            if (!this.audioDevices().length) {
                const devices = await navigator.mediaDevices.enumerateDevices();
                this.audioDevices.set(devices.filter((d) => d.kind === 'audioinput'));
                this.isInitialized.set(true);
                this.attachDeviceListener();
            }
            return success;
        } catch (error) {
            console.error('Error initializing recording:', error);
            return false;
        }
    }

    public startRecording(
        audioCallback?: (data: { mono: Int16Array; raw: Int16Array }) => void,
        chunkSize: number = 8192
    ): Promise<boolean> {
        void chunkSize;
        this.isRecording.set(true);
        this.isPaused.set(false);

        const status: 'ended' | 'paused' | 'recording' = this.wavRecorder.getStatus();
        if (status === 'recording') {
            return Promise.resolve(true);
        }

        return this.wavRecorder
            .record(audioCallback || (() => {}), 8192)
            .then((success) => success)
            .catch((error) => {
                console.error('Error starting recording:', error);
                this.isRecording.set(false);
                return false;
            });
    }

    public pauseRecording(): Promise<boolean> {
        if (this.wavRecorder.getStatus() === 'recording') {
            return this.wavRecorder
                .pause()
                .then((success) => {
                    if (success) {
                        this.isPaused.set(true);
                        this.isRecording.set(false);
                    }
                    return success;
                })
                .catch((error) => {
                    console.error('Error pausing recording:', error);
                    return false;
                });
        }
        return Promise.resolve(false);
    }

    public stopRecording(): Promise<boolean> {
        this.isRecording.set(false);
        this.isPaused.set(false);
        return this.wavRecorder
            .end()
            .then(() => true)
            .catch((error) => {
                console.error('Error stopping recording:', error);
                return false;
            });
    }

    public clearRecording(): Promise<boolean> {
        return this.wavRecorder
            .clear()
            .then((success) => success)
            .catch((error) => {
                console.error('Error clearing recording:', error);
                return false;
            });
    }

    public getStatus(): 'ended' | 'recording' | 'paused' {
        return this.wavRecorder.getStatus();
    }

    public getFrequencyData(
        analysisType: 'frequency' | 'music' | 'voice' = 'frequency',
        minDecibels: number = -100,
        maxDecibels: number = -30
    ): AudioAnalysisOutputType {
        return this.wavRecorder.getFrequencies(analysisType, minDecibels, maxDecibels);
    }
}
