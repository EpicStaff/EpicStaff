// microphone-selector.component.ts
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, effect, inject, OnInit } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { WavRecorderService } from '../../../../../services/wav-recorder.service';

const STORAGE_KEY_DEVICE_ID = 'selected_microphone_id';

@Component({
    selector: 'app-microphone-selector',
    templateUrl: './microphone-selector.component.html',
    styleUrls: ['./microphone-selector.component.scss'],
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MicrophoneSelectorComponent implements OnInit {
    public showDevicesList = false;
    public selectedDeviceId = '';

    // Inject WavRecorderService
    private wavRecorderService = inject(WavRecorderService);
    private cdr = inject(ChangeDetectorRef);

    constructor() {
        // Watch for changes in the devices list
        effect(() => {
            // This effect will run whenever audioDevices signal changes
            const devices = this.wavRecorderService.audioDevices();

            // If we have devices and no device is selected, initialize one
            if (devices.length > 0 && !this.selectedDeviceId) {
                this.initializeDevice();
            }

            this.cdr.markForCheck();
        });
    }

    ngOnInit(): void {
        // The initial device selection will be handled by the effect
    }

    private initializeDevice(): void {
        // If already initialized, don't do it again
        if (this.selectedDeviceId) return;

        // Try to get saved device
        const savedDeviceId = localStorage.getItem(STORAGE_KEY_DEVICE_ID);

        if (savedDeviceId) {
            const savedDevice = this.audioInputDevices.find((d) => d.deviceId === savedDeviceId);
            if (savedDevice) {
                this.selectedDeviceId = savedDevice.deviceId;
                return;
            }
        }

        // Use default or first device
        const defaultDevice = this.audioInputDevices.find((d: MediaDeviceInfo) => d.deviceId === 'default');

        if (defaultDevice) {
            this.selectedDeviceId = defaultDevice.deviceId;
        } else if (this.audioInputDevices.length > 0) {
            this.selectedDeviceId = this.audioInputDevices[0].deviceId;
        }
    }

    public toggleDevicesList(event: Event): void {
        event.stopPropagation();

        // Only toggle if we have devices
        if (this.hasDevices) {
            this.showDevicesList = !this.showDevicesList;
            this.cdr.markForCheck();
        }
    }

    public selectDevice(deviceId: string): void {
        this.selectedDeviceId = deviceId;
        localStorage.setItem(STORAGE_KEY_DEVICE_ID, deviceId);
        this.showDevicesList = false;
        this.cdr.markForCheck();
    }

    public getSelectedDeviceLabel(): string {
        const selectedDevice = this.audioInputDevices.find((d) => d.deviceId === this.selectedDeviceId);
        return selectedDevice?.label || 'Default microphone';
    }

    public get audioInputDevices(): MediaDeviceInfo[] {
        return this.wavRecorderService.audioDevices().filter((device) => device.kind === 'audioinput');
    }

    public get hasDevices(): boolean {
        return this.audioInputDevices.length > 0;
    }

    public get isInitialized(): boolean {
        return this.wavRecorderService.isInitialized();
    }
}
