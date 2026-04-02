import { DestroyRef, inject, Injectable, signal } from '@angular/core';
import { WavRecorder } from 'wavtools';
import { AudioAnalysisOutputType } from 'wavtools/dist/lib/analysis/audio_analysis';

@Injectable({
    providedIn: 'root',
})
export class WavRecorderService {
    private wavRecorder: WavRecorder;
    private destroyRef = inject(DestroyRef);

    // Essential signals
    public audioDevices = signal<MediaDeviceInfo[]>([]);
    public isRecording = signal<boolean>(false);
    public isPaused = signal<boolean>(false);
    public isInitialized = signal<boolean>(false);

    constructor() {
        // 1. Probe sampleRate on Firefox, otherwise default to 24000
        const isFirefox = navigator.userAgent.includes('Firefox');
        let sampleRate: number;

        if (isFirefox) {
            const probeCtx = new AudioContext();
            sampleRate = probeCtx.sampleRate;
            console.log('Detected audio sample rate (Firefox):', sampleRate);
            probeCtx.close();
        } else {
            sampleRate = 24000;
            console.log('Using default sample rate:', sampleRate);
        }

        // 2. Instantiate recorder
        this.wavRecorder = new WavRecorder({ sampleRate });

        // 3. Usual init
        this.initialize();
    }

    /**
     * Initialize the recorder and setup device detection
     */
    private initialize(): void {
        this.listAudioDevices();

        this.wavRecorder.listenForDeviceChange((devices: MediaDeviceInfo[]) => {
            this.audioDevices.set(devices);
            console.log('Audio devices updated:', devices);
        });
    }

    /**
     * List available audio input devices
     * @returns Promise<MediaDeviceInfo[]>
     */
    public listAudioDevices(): Promise<MediaDeviceInfo[]> {
        return this.wavRecorder
            .listDevices()
            .then((devices: MediaDeviceInfo[]) => {
                this.audioDevices.set(devices);
                this.isInitialized.set(true);
                return devices;
            })
            .catch((error) => {
                console.error('Error listing audio devices:', error);
                return [];
            });
    }

    /**
     * Begin recording session with optional device ID
     * @param deviceId Optional device ID to use for recording
     * @returns Promise<boolean> True if recording was initialized successfully
     */

    public async beginRecording(deviceId?: string): Promise<boolean> {
        const isFirefox = navigator.userAgent.includes('Firefox');
        if (isFirefox) {
            // alert only when we actually begin
            window.alert(
                '⚠️ Voice capture on Firefox can be unreliable—OpenAI’s voice recognition may perform poorly here.'
            );
        }

        try {
            const success = await this.wavRecorder.begin(deviceId);
            console.log('Recording initialized:', success);
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
        // Update state signals
        this.isRecording.set(true);
        this.isPaused.set(false);

        const status: 'ended' | 'paused' | 'recording' = this.wavRecorder.getStatus();

        // Already recording
        if (status === 'recording') {
            console.warn('Already recording.');
            return Promise.resolve(true);
        }

        // Start or resume recording
        return this.wavRecorder
            .record(audioCallback || (() => {}), 8192)
            .then((success) => {
                console.log(`Recording ${status === 'paused' ? 'resumed' : 'started'}:`, success);
                return success;
            })
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
                        console.log('Recording paused');
                    }
                    return success;
                })
                .catch((error) => {
                    console.error('Error pausing recording:', error);
                    return false;
                });
        } else {
            console.warn('Cannot pause because recorder is not recording.');
            return Promise.resolve(false);
        }
    }

    public stopRecording(): Promise<boolean> {
        this.isRecording.set(false);
        this.isPaused.set(false);

        return this.wavRecorder
            .end()
            .then(() => {
                console.log('Recording stopped');
                return true;
            })
            .catch((error) => {
                console.error('Error stopping recording:', error);
                return false;
            });
    }

    public clearRecording(): Promise<boolean> {
        return this.wavRecorder
            .clear()
            .then((success) => {
                console.log('Recording cleared');
                return success;
            })
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
