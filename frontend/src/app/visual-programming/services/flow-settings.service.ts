import { effect, Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class FlowSettingsService {
    private static readonly STORAGE_KEY = 'flow-settings';

    readonly arrowColorsEnabled = signal<boolean>(true);
    readonly showInputsOutputs = signal<boolean>(false);
    readonly showNodeNumbersInTitles = signal<boolean>(false);
    readonly timezone = signal<string>(FlowSettingsService.defaultTimezone());

    constructor() {
        this.loadFromStorage();
        effect(() => this.saveToStorage());
    }

    private static defaultTimezone(): string {
        const raw = Intl.DateTimeFormat().resolvedOptions().timeZone;
        return raw === 'Europe/Kiev' ? 'Europe/Kyiv' : raw;
    }

    private loadFromStorage(): void {
        try {
            const raw = localStorage.getItem(FlowSettingsService.STORAGE_KEY);
            if (!raw) return;
            const parsed = JSON.parse(raw) as Record<string, unknown>;
            if (typeof parsed['arrowColors'] === 'boolean') this.arrowColorsEnabled.set(parsed['arrowColors']);
            if (typeof parsed['showInputsOutputs'] === 'boolean')
                this.showInputsOutputs.set(parsed['showInputsOutputs']);
            if (typeof parsed['showNodeNumbersInTitles'] === 'boolean')
                this.showNodeNumbersInTitles.set(parsed['showNodeNumbersInTitles']);
            if (typeof parsed['timezone'] === 'string' && parsed['timezone']) this.timezone.set(parsed['timezone']);
        } catch {
            // fallback to defaults
        }
    }

    private saveToStorage(): void {
        localStorage.setItem(
            FlowSettingsService.STORAGE_KEY,
            JSON.stringify({
                arrowColors: this.arrowColorsEnabled(),
                showInputsOutputs: this.showInputsOutputs(),
                showNodeNumbersInTitles: this.showNodeNumbersInTitles(),
                timezone: this.timezone(),
            })
        );
    }
}
