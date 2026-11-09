import { ChangeDetectionStrategy, Component, computed, input, linkedSignal, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HintMessageComponent, ToggleSwitchComponent } from '@shared/components';

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
    selector: 'app-node-storage-section',
    imports: [FormsModule, HintMessageComponent, ToggleSwitchComponent],
    template: `
        <div class="storage-section">
            <div class="storage-header">
                <span class="section-label">Enable Storage</span>
                <app-toggle-switch
                    ariaLabel="Enable Storage"
                    [disabled]="readonly() || !!shownLockReason()"
                    [checked]="enabled()"
                    (checkedChange)="onToggle($event)"
                ></app-toggle-switch>
            </div>
            @if (shownLockReason(); as reason) {
                <app-hint-message tone="warning">{{ reason }}</app-hint-message>
            }
        </div>
    `,
    styleUrl: './node-storage-section.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NodeStorageSectionComponent {
    readonly useStorage = input.required<boolean>();
    readonly readonly = input<boolean>(false);
    /** Why the switch may not be turned on, shown under it; the switch is disabled while set. */
    readonly lockReason = input<string | null>(null);
    /** The reason is shown only when it is the sole blocker: a read-only section already says nothing can change. */
    protected readonly shownLockReason = computed(() => (this.readonly() ? null : this.lockReason()));

    readonly onInsertCode = output<string>();
    readonly onRemoveCode = output<string>();
    readonly onToggleChange = output<boolean>();

    /** Follows `useStorage`, so a panel reused for another node shows that node's flag. */
    readonly enabled = linkedSignal(() => this.useStorage());

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
