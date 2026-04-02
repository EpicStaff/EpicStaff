import { Injectable, signal } from '@angular/core';
import { WavStreamPlayer } from 'wavtools';
import { AudioAnalysisOutputType } from 'wavtools/dist/lib/analysis/audio_analysis';

@Injectable({
    providedIn: 'root',
})
export class WavStreamPlayerService {
    private wavStreamPlayer: WavStreamPlayer;

    // Signals
    public isPlayerConnected = signal<boolean>(false);

    constructor() {
        // Initialize WavStreamPlayer with default settings
        this.wavStreamPlayer = new WavStreamPlayer({ sampleRate: 24000 });
    }

    /**
     * Connects the audio context and enables output to speakers
     * @returns {Promise<boolean>} True if connection was successful
     */
    public connect(): Promise<boolean> {
        return this.wavStreamPlayer
            .connect()
            .then((success) => {
                this.isPlayerConnected.set(true);
                console.log('WavStreamPlayer connected successfully');
                return success;
            })
            .catch((error) => {
                console.error('Error connecting WavStreamPlayer:', error);
                return false;
            });
    }

    /**
     * Adds 16BitPCM data to the currently playing audio stream
     * @param {ArrayBuffer|Int16Array} arrayBuffer Audio data as ArrayBuffer or Int16Array
     * @param {string} trackId Optional track identifier, defaults to 'default'
     * @returns {Int16Array|undefined} The processed buffer or undefined if operation fails
     */
    public add16BitPCM(arrayBuffer: ArrayBuffer | Int16Array, trackId: string = 'default'): Int16Array | undefined {
        try {
            return this.wavStreamPlayer.add16BitPCM(arrayBuffer, trackId);
        } catch (error) {
            console.error('Error adding PCM data:', error);
            return undefined;
        }
    }

    /**
     * Gets the current frequency domain data from the playing track
     * @param {string} analysisType Type of analysis ('frequency', 'music', 'voice')
     * @param {number} minDecibels Minimum decibels value
     * @param {number} maxDecibels Maximum decibels value
     * @returns {AudioAnalysisOutputType} Frequency data analysis
     */
    public getFrequencyData(
        analysisType: 'frequency' | 'music' | 'voice' = 'frequency',
        minDecibels: number = -100,
        maxDecibels: number = -30
    ): AudioAnalysisOutputType {
        if (!this.isPlayerConnected()) {
            return {
                values: new Float32Array(0),
                frequencies: [],
                labels: [],
            };
        }

        try {
            return this.wavStreamPlayer.getFrequencies(analysisType, minDecibels, maxDecibels);
        } catch (error) {
            console.error('Error getting frequency data:', error);
            // Return empty frequency data that matches AudioAnalysisOutputType
            return {
                values: new Float32Array(0),
                frequencies: [],
                labels: [],
            };
        }
    }

    /**
     * Interrupts the current stream and returns the sample offset
     * @returns {Promise<{trackId: string | null; offset: number; currentTime: number;}>}
     */
    public async interrupt(): Promise<{
        trackId: string | null;
        offset: number;
        currentTime: number;
    }> {
        if (!this.isPlayerConnected()) {
            console.warn('Cannot interrupt: Not connected to audio stream');
            return { trackId: null, offset: 0, currentTime: 0 };
        }

        try {
            const result = await this.wavStreamPlayer.interrupt();

            // Check if result is null or undefined before accessing properties
            if (!result) {
                console.warn('Stream interrupt returned null result');
                return { trackId: null, offset: 0, currentTime: 0 };
            }

            console.log('Stream interrupted at offset:', result.offset);
            return result;
        } catch (error) {
            console.error('Error interrupting stream:', error);
            return { trackId: null, offset: 0, currentTime: 0 };
        }
    }

    /**
     * Gets the current sample offset of the track
     * @param {boolean} interrupt Whether to interrupt the track
     * @returns {Promise<{trackId: string | null; offset: number; currentTime: number;} | null>}
     */
    public async getTrackSampleOffset(interrupt: boolean = false): Promise<{
        trackId: string | null;
        offset: number;
        currentTime: number;
    } | null> {
        if (!this.isPlayerConnected()) {
            console.warn('Cannot get track sample offset: Not connected to audio stream');
            return null;
        }

        try {
            const result = await this.wavStreamPlayer.getTrackSampleOffset(interrupt);

            // Check if result is null or undefined before returning
            if (!result) {
                return null;
            }

            return result;
        } catch (error) {
            console.error('Error getting track sample offset:', error);
            return null;
        }
    }
}
