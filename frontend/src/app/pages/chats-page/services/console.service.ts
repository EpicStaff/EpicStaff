import { HttpClient, HttpHeaders } from '@angular/common/http';
import { DestroyRef, inject, Injectable, OnDestroy, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ItemType } from '@openai/realtime-api-beta/dist/lib/client.js';
import { EMPTY, from, fromEvent, Observable, of, Subject } from 'rxjs';
import { catchError, delay, map, switchMap, tap } from 'rxjs/operators';

import { ConfigService } from '../../../services/config/config.service';
import { ToastService } from '../../../services/notifications/toast.service';
// @ts-ignore
import { RealtimeClient } from '../libs/openai/client';
import { ChatsService } from './chats.service';
import { WavStreamPlayerService } from './wav-player.service';
import { WavRecorderService } from './wav-recorder.service';

export interface InitRealtime {
    agent_id: number;
}

export interface ConnectionResult {
    success: boolean;
    error?: Error;
}

@Injectable({
    providedIn: 'root',
})
export class ConsoleService implements OnDestroy {
    private get apiUrl(): string {
        return this.configService.apiUrl + 'init-realtime/';
    }
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private client!: RealtimeClient | null;
    private destroyRef = inject(DestroyRef);
    private isDisconnecting = false;

    // Signals
    public items = signal<ItemType[]>([]);
    public isConnected = signal<boolean>(false);
    public currentVoice = signal<string>('verse');
    public isClientConnected = signal<boolean>(false);
    public isConversationConnected = signal<boolean>(false);

    // Subjects
    private connectionError$ = new Subject<Error>();

    constructor(
        private http: HttpClient,
        private chatsService: ChatsService,
        private toastService: ToastService,
        private configService: ConfigService,
        private wavRecorderService: WavRecorderService,
        private wavStreamPlayerService: WavStreamPlayerService
    ) {
        this.connectionError$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((error) => {
            console.error('Connection error:', error);
            this.isConnected.set(false);
        });
    }

    ngOnDestroy(): void {
        this.disconnectConversation();
        this.connectionError$.complete();
    }

    private connectToRealtime(): void {
        this.client = new RealtimeClient({
            url: this.configService.realtimeApiUrl,
            dangerouslyAllowAPIKeyInBrowser: false,
        });
        this.setupClient();
    }

    /**
     * Connects to a conversation
     * @returns Observable<ConnectionResult> - Observable that emits the connection result
     */
    connectConversation(): Observable<ConnectionResult> {
        if (this.isClientConnected() || this.isConversationConnected()) {
            // First disconnect if already connected
            this.disconnectConversation();
            // Add slight delay to ensure clean state before reconnecting
            return of(null).pipe(
                delay(300),
                switchMap((): Observable<ConnectionResult> => this.initiateConnection())
            );
        } else {
            return this.initiateConnection();
        }
    }

    /**
     * Internal method to handle the connection process
     * @returns Observable<ConnectionResult>
     */
    private initiateConnection(): Observable<ConnectionResult> {
        const selectedAgent = this.chatsService.selectedAgent$();

        if (!selectedAgent?.realtime_agent.realtime_config) {
            this.toastService.warning('The selected agent does not have Realtime LLM specified');
            return of<ConnectionResult>({
                success: false,
                error: new Error('No Realtime LLM specified'),
            });
        }

        if (!selectedAgent?.id) {
            this.toastService.warning('The selected agent does not have a valid ID');
            return of<ConnectionResult>({
                success: false,
                error: new Error('No agent ID found'),
            });
        }

        if (!selectedAgent?.realtime_agent.realtime_transcription_config) {
            this.toastService.warning('The selected agent does not have a transcription config');
            return of<ConnectionResult>({
                success: false,
                error: new Error('No transcription config'),
            });
        }

        const payload: InitRealtime = {
            agent_id: selectedAgent.id,
        };
        return this.http
            .post<{ connection_key: string }>(this.apiUrl, payload, {
                headers: this.headers,
            })
            .pipe(
                tap((response) => {
                    console.log('POST Response:', response);
                    if (response.connection_key) {
                        localStorage.setItem('connectionKey', response.connection_key);
                    } else {
                        throw new Error('connection_key is missing in the response');
                    }
                }),
                delay(200),
                takeUntilDestroyed(this.destroyRef),

                switchMap(() => {
                    const storedKey: string | null = localStorage.getItem('connectionKey');
                    console.log('Retrieved connectionKey:', storedKey);

                    if (!storedKey) {
                        throw new Error('No connectionKey found in localStorage');
                    }

                    this.connectToRealtime();
                    this.updateItems();

                    // Begin a sequence of initialization steps
                    return this.initializeServices();
                }),
                // Return success result
                map((): ConnectionResult => ({ success: true })),
                // Handle errors and return failure result
                catchError((error: Error) => {
                    this.connectionError$.next(error);
                    this.cleanupAfterFailedConnection();
                    return of<ConnectionResult>({ success: false, error });
                })
            );
    }

    // Add this property to your class
    private savedAudioCallback: ((data: { mono: Int16Array; raw: Int16Array }) => void) | null = null;

    // Add this helper method
    private getAudioCallback(): (data: { mono: Int16Array; raw: Int16Array }) => void {
        if (!this.savedAudioCallback) {
            this.savedAudioCallback = (data: { mono: Int16Array; raw: Int16Array }) => {
                if (this.client) {
                    this.client.appendInputAudio(data.mono);
                }
            };
        }
        return this.savedAudioCallback;
    }

    /**
     * Initialize all services needed for the conversation
     * @returns Observable that completes when all services are initialized
     */
    private initializeServices(): Observable<void> {
        return from(this.wavRecorderService.beginRecording()).pipe(
            // Connect player
            switchMap(() => from(this.wavStreamPlayerService.connect())),
            // Connect client
            switchMap(() => {
                if (!this.client) {
                    throw new Error('Client is not initialized');
                }
                return from(this.client.connect());
            }),
            // Update status
            tap(() => {
                this.isClientConnected.set(true);
            }),
            // Start recording with saved callback
            switchMap(() => {
                return from(this.wavRecorderService.startRecording(this.getAudioCallback(), 8192));
            }),
            // Update status
            tap(() => {
                this.isConversationConnected.set(true);
                this.isConnected.set(true);
            }),
            // Return void for simple typing
            map(() => void 0)
        );
    }

    public resumeRecording(): Promise<boolean> {
        return this.wavRecorderService.startRecording(this.getAudioCallback(), 8192);
    }

    private cleanupAfterFailedConnection(): void {
        // Clean up any resources that might have been initialized
        if (this.client) {
            try {
                this.client.disconnect();
                this.client = null;
            } catch (error) {
                console.error('Error cleaning up client:', error);
            }
        }

        this.isClientConnected.set(false);
        this.isConversationConnected.set(false);
        this.isConnected.set(false);

        // Attempt to stop recording if it was started
        this.wavRecorderService.stopRecording().catch((error) => {
            console.error('Error stopping recorder during cleanup:', error);
        });
    }

    async disconnectConversation(): Promise<boolean> {
        if (!this.isConversationConnected() || this.isDisconnecting) return true;

        this.isDisconnecting = true;

        try {
            // Stop recording first
            await this.wavRecorderService.stopRecording();

            // Then interrupt player
            if (this.wavStreamPlayerService) {
                const interruptResult = await this.wavStreamPlayerService.interrupt();
                console.log('Interrupt result:', interruptResult);

                // Check if we need to cancel the response based on the interrupt result
                if (interruptResult?.trackId && this.client) {
                    const { trackId, offset } = interruptResult;
                    this.client.cancelResponse(trackId, offset);
                }
            }

            // Disconnect client
            if (this.client) {
                this.client.disconnect();
                this.items.set([]);
                this.client.reset();
                this.client = null;
            }

            // Update connection states
            this.isClientConnected.set(false);
            this.isConversationConnected.set(false);
            this.isConnected.set(false);

            return true;
        } catch (error) {
            console.error('Error disconnecting conversation:', error);
            // Even on error, we should reset our state
            this.isClientConnected.set(false);
            this.isConversationConnected.set(false);
            this.isConnected.set(false);
            return false;
        } finally {
            this.isDisconnecting = false;
        }
    }

    deleteConversationItem(id: string): void {
        if (!this.client || !id) {
            console.warn('Cannot delete item: Client not connected or invalid ID');
            return;
        }

        this.client.deleteItem(id);
        of(null)
            .pipe(
                delay(100),
                tap(() => this.updateItems())
            )
            .subscribe();
    }

    //   private updateItems(): void {
    //     if (this.client) {
    //       this.items.set(this.client.conversation.getItems());
    //     }
    //   }
    private updateItems(): void {
        if (this.client) {
            // Get all items from the conversation
            const allItems = this.client.conversation.getItems();

            // Create a map to store call_ids of wikipedia and knowledge_tool function calls
            const toolCallIds = new Set<string>();

            // First pass: identify all call_ids from wikipedia or knowledge_tool function calls
            allItems.forEach((item) => {
                if (item.type === 'function_call' && item.name === 'stop_agent_tool') {
                    if (item.call_id) {
                        toolCallIds.add(item.call_id);
                    }
                }
            });

            // Second pass: filter out both the tool items and their outputs
            const filteredItems = allItems.filter((item) => {
                // Filter out wikipedia/knowledge_tool function calls
                if (item.type === 'function_call' && item.name === 'stop_agent_tool') {
                    return false;
                }

                // Filter out function_call_outputs that match the tool call_ids
                if (item.type === 'function_call_output' && item.call_id && toolCallIds.has(item.call_id)) {
                    return false;
                }

                return true;
            });

            // Set the filtered items
            this.items.set(filteredItems);
        } else {
            this.items.set([]);
        }
    }
    private setupClient(): void {
        if (!this.client) return;

        // Configure transcription
        this.client.updateSession({
            input_audio_transcription: { model: 'whisper-1' },
        });

        // Configure turn detection
        this.client.updateSession({
            turn_detection: { type: 'server_vad' },
        });

        // Error handling
        fromEvent(this.client, 'error')
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((event: unknown) => console.error('Client error:', event));

        // Interruption handling
        fromEvent(this.client, 'conversation.interrupted')
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(async () => {
                    try {
                        const interruptResult = await this.wavStreamPlayerService.interrupt();
                        if (interruptResult?.trackId && this.client) {
                            const { trackId, offset } = interruptResult;
                            this.client.cancelResponse(trackId, offset);
                        }
                        return interruptResult;
                    } catch (error) {
                        console.error('Error interrupting conversation:', error);
                        throw error;
                    }
                }),
                catchError((error) => {
                    console.error('Error in interruption handler:', error);
                    return EMPTY;
                })
            )
            .subscribe();

        // Conversation updates
        fromEvent<{ item: { id: string }; delta: { audio?: Int16Array } | null }>(this.client, 'conversation.updated')
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(({ item, delta }) => {
                    if (delta?.audio) {
                        this.wavStreamPlayerService.add16BitPCM(delta.audio, item.id);
                    }
                    this.updateItems();
                }),
                catchError((error) => {
                    console.error('Error updating conversation:', error);
                    return EMPTY;
                })
            )
            .subscribe();

        this.updateItems();
    }

    /**
     * Sends a text message to the conversation
     * @param message - The text message to send
     * @returns boolean - Whether the message was sent successfully
     */
    async sendTextMessage(message: string): Promise<boolean> {
        if (!this.isConversationConnected() || !this.isClientConnected() || !this.client || !message) {
            console.warn('Cannot send message: Not connected or empty message');
            return false;
        }

        try {
            this.client.sendUserMessageContent([{ type: 'input_text', text: message }]);
            await this.wavStreamPlayerService.interrupt();

            return true;
        } catch (error) {
            console.error('Error sending message:', error);
            return false;
        }
    }
    resumeAudioStream(): void {
        if (!this.client) return;

        this.wavRecorderService.startRecording((data: { mono: Int16Array; raw: Int16Array }) => {
            if (this.client) {
                this.client.appendInputAudio(data.mono);
            }
        }, 8192);
    }
    /**
     * Gets stream frequency data for visualizations
     * @param analysisType - Type of analysis to perform
     * @param minDecibels - Minimum decibels for analysis
     * @param maxDecibels - Maximum decibels for analysis
     * @returns Analysis data from the stream player
     */
    public getStreamFrequencyData(
        analysisType: 'frequency' | 'music' | 'voice' = 'frequency',
        minDecibels: number = -100,
        maxDecibels: number = -30
    ) {
        return this.wavStreamPlayerService.getFrequencyData(analysisType, minDecibels, maxDecibels);
    }
}
