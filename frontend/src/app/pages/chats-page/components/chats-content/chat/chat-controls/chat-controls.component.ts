import {
    ChangeDetectionStrategy,
    Component,
    effect,
    ElementRef,
    inject,
    OnInit,
    signal,
    viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { CollapseOnOverflowDirective } from '@shared/directives';
import { from } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications';
import { ConsoleService } from '../../../../services/console.service';
import { WavRecorderService } from '../../../../services/wav-recorder.service';
import { MicrophoneSelectorComponent } from './microphone-selector/microphone-selector.component';
import { VoiceVisualizerComponent } from './voice-visualizer/voice-visualizer.component';

type ChatControlsFocusTarget = 'recording-controls' | 'start-speaking' | 'message';

@Component({
    selector: 'app-chat-controls',
    imports: [
        FormsModule,
        MicrophoneSelectorComponent,
        VoiceVisualizerComponent,
        AppSvgIconComponent,
        MatTooltip,
        CollapseOnOverflowDirective,
    ],
    templateUrl: './chat-controls.component.html',
    styleUrls: ['./chat-controls.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatControlsComponent implements OnInit {
    // Each control set replaces the other, and keyboard mode adds the message field: the focus follows to the new
    // set instead of falling to the page.
    private readonly startSpeakingButton = viewChild<ElementRef<HTMLButtonElement>>('startSpeakingButton');
    private readonly keyboardToggle = viewChild<ElementRef<HTMLButtonElement>>('keyboardToggle');
    private readonly messageInput = viewChild<ElementRef<HTMLTextAreaElement>>('messageInput');

    // Use signals for reactive state management
    isKeyboardMode = signal<boolean>(false);
    isMicrophoneMuted = signal<boolean>(false);
    isConnecting = signal<boolean>(false);
    isRecorderInitialized = signal<boolean>(false);
    private readonly pendingFocus = signal<ChatControlsFocusTarget | null>(null);

    private readonly movePendingFocus = effect(() => {
        const target = this.pendingFocus();
        if (target === null) return;
        const element = {
            'recording-controls': this.keyboardToggle(),
            'start-speaking': this.startSpeakingButton(),
            message: this.messageInput(),
        }[target];
        if (!element) return;
        element.nativeElement.focus();
        this.pendingFocus.set(null);
    });

    messageText = '';

    wavRecorderService = inject(WavRecorderService);
    private readonly toastService = inject(ToastService);

    constructor(public consoleService: ConsoleService) {
        effect(() => {
            this.isRecorderInitialized.set(this.wavRecorderService.isInitialized());
        });
    }

    ngOnInit(): void {
        this.updateMicrophoneState();
    }

    private updateMicrophoneState(): void {
        this.isMicrophoneMuted.set(this.wavRecorderService.getStatus() === 'paused');
    }

    /**
     * Request mic under this click first, then connect. Otherwise validation
     * errors (e.g. missing transcription) abort before any permission prompt.
     */
    onStartSpeaking(): void {
        if (!this.canStartSpeaking()) {
            return;
        }

        this.isConnecting.set(true);
        this.pendingFocus.set('recording-controls');

        from(this.wavRecorderService.ensureDevicesReady())
            .pipe(
                switchMap((devices) => {
                    if (!devices.length) {
                        this.toastService.warning('Microphone permission is required to start speaking');
                        return from([{ success: false as const, error: new Error('Microphone permission denied') }]);
                    }
                    return this.consoleService.connectConversation();
                })
            )
            .subscribe({
                next: (result) => {
                    this.isConnecting.set(false);
                    if (result.success) {
                        this.updateMicrophoneState();
                    } else {
                        this.pendingFocus.set(null);
                        console.error('Failed to connect conversation:', result.error);
                    }
                },
                error: (error) => {
                    this.isConnecting.set(false);
                    this.pendingFocus.set(null);
                    console.error('Error connecting conversation:', error);
                },
            });
    }

    /**
     * Start Speaking is always available while idle — mic permission is requested
     * on click (or devices are already known if permission was previously granted).
     */
    canStartSpeaking(): boolean {
        return !this.isConnecting();
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
        this.pendingFocus.set('start-speaking');
    }

    /**
     * Toggle between keyboard and microphone input modes
     */
    toggleInputMode(): void {
        const newKeyboardMode = !this.isKeyboardMode();
        this.isKeyboardMode.set(newKeyboardMode);

        if (newKeyboardMode) {
            this.pendingFocus.set('message');
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
