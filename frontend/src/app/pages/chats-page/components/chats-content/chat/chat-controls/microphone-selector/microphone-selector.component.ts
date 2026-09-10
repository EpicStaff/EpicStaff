import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    signal,
    ViewChild,
} from '@angular/core';
import { SelectComponent, SelectItem } from '@shared/components';

import { SELECTED_MICROPHONE_STORAGE_KEY, WavRecorderService } from '../../../../../services/wav-recorder.service';

@Component({
    selector: 'app-microphone-selector',
    templateUrl: './microphone-selector.component.html',
    styleUrls: ['./microphone-selector.component.scss'],
    imports: [SelectComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MicrophoneSelectorComponent implements AfterViewInit {
    @ViewChild(SelectComponent) private selectRef?: SelectComponent;

    private readonly wavRecorderService = inject(WavRecorderService);
    private readonly cdr = inject(ChangeDetectorRef);
    private readonly host = inject(ElementRef<HTMLElement>);
    private readonly destroyRef = inject(DestroyRef);

    readonly selectedDeviceId = signal<string | null>(null);

    readonly deviceItems = computed<SelectItem<string>[]>(() =>
        this.wavRecorderService
            .audioDevices()
            .filter((device) => device.kind === 'audioinput')
            .map((device) => ({
                name: device.label || 'Unnamed device',
                value: device.deviceId,
            }))
    );

    readonly isLoadingDevices = computed(() => this.wavRecorderService.isLoadingDevices());

    readonly placeholder = computed(() => {
        if (this.wavRecorderService.permissionBlocked()) {
            return 'Microphone blocked — click to retry';
        }
        if (this.wavRecorderService.isInitialized() && this.deviceItems().length === 0) {
            return 'No microphones found — click to retry';
        }
        return 'Default microphone';
    });

    private readonly onClickCapture = (event: Event) => {
        void this.handleClickCapture(event);
    };

    constructor() {
        this.destroyRef.onDestroy(() => {
            this.host.nativeElement.removeEventListener('click', this.onClickCapture, true);
        });
    }

    ngAfterViewInit(): void {
        this.host.nativeElement.addEventListener('click', this.onClickCapture, true);
    }

    onDeviceChanged(value: unknown): void {
        if (typeof value !== 'string' || !value) return;
        this.selectedDeviceId.set(value);
        localStorage.setItem(SELECTED_MICROPHONE_STORAGE_KEY, value);
    }

    private async handleClickCapture(event: Event): Promise<void> {
        if (this.isLoadingDevices()) {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }

        // First open (or retry after empty/blocked): load devices under this user gesture,
        // then open app-select — otherwise the panel opens empty / permission is lost.
        if (this.deviceItems().length > 0) {
            return;
        }

        event.preventDefault();
        event.stopImmediatePropagation();

        await this.wavRecorderService.ensureDevicesReady();
        this.syncSelection();
        this.cdr.detectChanges();

        if (this.deviceItems().length > 0) {
            this.selectRef?.openDropdown();
        }
    }

    private syncSelection(): void {
        const items = this.deviceItems();
        if (!items.length) {
            this.selectedDeviceId.set(null);
            return;
        }

        const current = this.selectedDeviceId();
        if (current && items.some((i) => i.value === current)) return;

        const saved = localStorage.getItem(SELECTED_MICROPHONE_STORAGE_KEY);
        if (saved && items.some((i) => i.value === saved)) {
            this.selectedDeviceId.set(saved);
            return;
        }

        const defaultItem = items.find((i) => i.value === 'default');
        const next = defaultItem?.value ?? items[0].value;
        this.selectedDeviceId.set(next);
        localStorage.setItem(SELECTED_MICROPHONE_STORAGE_KEY, next);
    }
}
