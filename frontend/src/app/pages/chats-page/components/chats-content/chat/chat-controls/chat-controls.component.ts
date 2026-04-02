import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, effect, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CollapseOnOverflowDirective } from '../../../../../../shared/directives/collapse-on-overflow.directive';
import { ConsoleService } from '../../../../services/console.service';
import { WavRecorderService } from '../../../../services/wav-recorder.service';
import { MicrophoneSelectorComponent } from './microphone-selector/microphone-selector.component';
import { VoiceVisualizerComponent } from './voice-visualizer/voice-visualizer.component';

@Component({
    selector: 'app-chat-controls',
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        MicrophoneSelectorComponent,
        VoiceVisualizerComponent,
        CollapseOnOverflowDirective,
    ],
    templateUrl: './chat-controls.component.html',
    styleUrls: ['./chat-controls.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatControlsComponent implements OnInit {
    // Use signals for reactive state management
    isKeyboardMode = signal<boolean>(false);
    isMicrophoneMuted = signal<boolean>(false);
    isConnecting = signal<boolean>(false);
    isRecorderInitialized = signal<boolean>(false);

    messageText = '';

    wavRecorderService = inject(WavRecorderService);

    constructor(public consoleService: ConsoleService) {
        // React to changes in the WavRecorderService's initialization state
        effect(() => {
            this.isRecorderInitialized.set(this.wavRecorderService.isInitialized());
        });
    }

    ngOnInit(): void {
        // Initialize microphone muted state
        this.updateMicrophoneState();
    }

    /**
     * Update the internal microphone state from the service
     */
    private updateMicrophoneState(): void {
        this.isMicrophoneMuted.set(this.wavRecorderService.getStatus() === 'paused');
    }

    /**
     * Start a conversation
     */
    onStartSpeaking(): void {
        if (!this.canStartSpeaking()) {
            return;
        }

        this.isConnecting.set(true);

        this.consoleService.connectConversation().subscribe({
            next: (result) => {
                this.isConnecting.set(false);
                if (result.success) {
                    // Ensure microphone state is updated
                    this.updateMicrophoneState();
                } else {
                    console.error('Failed to connect conversation:', result.error);
                }
            },
            error: (error) => {
                this.isConnecting.set(false);
                console.error('Error connecting conversation:', error);
            },
        });
    }

    /**
     * Check if we can start speaking
     * Button should be disabled if connecting or if recorder is not initialized
     */
    canStartSpeaking(): boolean {
        return !this.isConnecting() && this.wavRecorderService.audioDevices().length > 0;
    }

    /**
     * Toggle microphone mute state
     */
    toggleRecording(): void {
        if (this.isMicrophoneMuted()) {
            // Resume recording using the saved callback
            this.consoleService.resumeRecording().then((success) => {
                if (success) {
                    this.isMicrophoneMuted.set(false);
                }
            });
        } else {
            // Pause recording
            this.wavRecorderService.pauseRecording().then((success) => {
                if (success) {
                    this.isMicrophoneMuted.set(true);
                }
            });
        }
    }

    /**
     * Stop the conversation
     */
    async stopConversation(): Promise<void> {
        try {
            const result = await this.consoleService.disconnectConversation();
            if (result) {
            } else {
                console.warn('Disconnection completed with issues');
            }
        } catch (error) {
            console.error('Error disconnecting conversation:', error);
        }

        // Reset UI state
        this.isKeyboardMode.set(false);
        this.isMicrophoneMuted.set(false);
    }

    /**
     * Toggle between keyboard and microphone input modes
     */
    toggleInputMode(): void {
        const newKeyboardMode = !this.isKeyboardMode();
        this.isKeyboardMode.set(newKeyboardMode);

        if (newKeyboardMode) {
            // Switching to keyboard mode - pause microphone if active
            if (!this.isMicrophoneMuted()) {
                this.wavRecorderService.pauseRecording().then((success) => {
                    if (success) {
                        this.isMicrophoneMuted.set(true);
                    }
                });
            }
        } else {
            // Switching to microphone mode - resume if muted
            if (this.isMicrophoneMuted()) {
                this.consoleService.resumeRecording().then((success) => {
                    if (success) {
                        this.isMicrophoneMuted.set(false);
                    }
                });
            }
        }
    }

    /**
     * Send a text message
     */
    sendMessage(): void {
        if (this.messageText.trim()) {
            this.consoleService.sendTextMessage(this.messageText);

            // Clear the input after sending
            this.messageText = '';
        }
    }

    /**
     * Check if the conversation is set up and ready
     */
    public get isConversationSetuped(): boolean {
        return this.consoleService.isClientConnected() && this.consoleService.isConversationConnected();
    }
}
