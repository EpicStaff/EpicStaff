import { ChangeDetectionStrategy, Component, input, OnInit, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ToggleSwitchComponent } from '../../../shared/components/form-controls/toggle-switch/toggle-switch.component';

const STORAGE_HEADER_COMMENT = `from epicstaff_storage import storage
# ── Storage API ─────────────────────────────────
# storage.read(path) → str          Read text file
# storage.read_bytes(path) → bytes  Read binary file
# storage.write(path, text)         Write text file
# storage.write_bytes(path, bytes)  Write binary file
# storage.list(path) → list         List folder contents
# storage.exists(path) → bool       Check if file exists
# storage.delete(path)              Delete file
# storage.mkdir(path)               Create folder
# storage.move(src, dst)            Move or rename
# storage.copy(src, dst)            Copy file
# storage.info(path) → dict         File metadata
# storage.as_local(path)            Context manager for temp local file
# ────────────────────────────────────────────────`;

@Component({
    standalone: true,
    selector: 'app-node-storage-section',
    imports: [FormsModule, ToggleSwitchComponent],
    template: `
        <div class="storage-section">
            <div class="storage-header">
                <span class="section-label">Enable Storage</span>
                <app-toggle-switch
                    [ngModel]="enabled()"
                    (ngModelChange)="onToggle($event)"
                ></app-toggle-switch>
            </div>
        </div>
    `,
    styleUrl: './node-storage-section.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NodeStorageSectionComponent implements OnInit {
    readonly useStorage = input.required<boolean>();

    readonly onInsertCode = output<string>();
    readonly onRemoveCode = output<string>();
    readonly onToggleChange = output<boolean>();

    readonly enabled = signal<boolean>(false);

    ngOnInit(): void {
        this.enabled.set(this.useStorage());
    }

    onToggle(value: boolean): void {
        this.enabled.set(value);
        this.onToggleChange.emit(value);
        if (value) {
            this.onInsertCode.emit(STORAGE_HEADER_COMMENT);
        } else {
            this.onRemoveCode.emit(STORAGE_HEADER_COMMENT);
        }
    }
}
