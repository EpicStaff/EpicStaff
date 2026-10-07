import { computed, Injectable, signal } from '@angular/core';
import { connect, type EpicStaffBridge, type InitContext, type ThemeMode } from '@epicstaff/plugin-sdk';

import { describeError } from './describe-error';

/**
 * The app's one connection to EpicStaff. `connect()` runs in the app initializer, before the
 * router's first navigation, so nav sync sees every URL change.
 *
 * Outside EpicStaff (e.g. `npm start` in a normal tab) the SDK answers from a mock host with
 * sample data; the mock is a lazy chunk, so the production app never downloads it.
 */
@Injectable({ providedIn: 'root' })
export class PluginBridgeService {
    private readonly bridgeSignal = signal<EpicStaffBridge | null>(null);
    private readonly errorSignal = signal<string | null>(null);
    private readonly themeModeSignal = signal<ThemeMode>('dark');

    readonly connected = computed(() => this.bridgeSignal() !== null);
    readonly connectionError = this.errorSignal.asReadonly();
    readonly context = computed<InitContext | null>(() => this.bridgeSignal()?.context ?? null);
    readonly mocked = computed(() => this.bridgeSignal()?.mocked ?? false);
    readonly themeMode = this.themeModeSignal.asReadonly();

    /** The connected bridge; throws before `connect()` succeeded. */
    get bridge(): EpicStaffBridge {
        const bridge = this.bridgeSignal();
        if (!bridge) throw new Error(this.errorSignal() ?? 'Not connected to EpicStaff yet.');
        return bridge;
    }

    /** Never rejects: a failed handshake is shown by the app shell instead of blocking bootstrap. */
    async connect(): Promise<void> {
        try {
            const bridge = await connect({
                mock: () => import('../mock/chat-admin-mock-host').then((module) => module.createChatAdminMockHost()),
            });
            this.themeModeSignal.set(bridge.theme.current.mode);
            bridge.theme.onChange((theme) => this.themeModeSignal.set(theme.mode));
            this.bridgeSignal.set(bridge);
        } catch (error) {
            this.errorSignal.set(`Could not connect to EpicStaff: ${describeError(error)}`);
        }
    }
}
