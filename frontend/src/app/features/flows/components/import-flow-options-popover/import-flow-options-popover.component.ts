import { CdkTrapFocus } from '@angular/cdk/a11y';
import { CdkOverlayOrigin, OverlayModule } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, EventEmitter, inject, Input, Output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { HelpTooltipComponent } from '@shared/components';

import { ImportFlowSettingsService } from '../../services/import-flow-settings.service';

@Component({
    selector: 'app-import-flow-options-popover',
    imports: [OverlayModule, CdkTrapFocus, MatTooltipModule, HelpTooltipComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './import-flow-options-popover.component.html',
    styleUrl: './import-flow-options-popover.component.scss',
})
export class ImportFlowOptionsPopoverComponent {
    @Input({ required: true }) public origin!: CdkOverlayOrigin;
    @Input() public open = false;
    @Output() public readonly closed = new EventEmitter<void>();

    private readonly settingsService = inject(ImportFlowSettingsService);
    public readonly settings = this.settingsService.settings;
    protected readonly canReplaceExisting = this.settingsService.canReplaceExisting;

    public readonly positions = [
        {
            originX: 'end' as const,
            originY: 'bottom' as const,
            overlayX: 'end' as const,
            overlayY: 'top' as const,
            offsetY: 6,
        },
        {
            originX: 'end' as const,
            originY: 'top' as const,
            overlayX: 'end' as const,
            overlayY: 'bottom' as const,
            offsetY: -6,
        },
    ];

    public setPreserveUuids(preserveUuids: boolean): void {
        this.settingsService.update({
            preserveUuids,
            ...(preserveUuids === false && { replaceExisting: false }),
        });
    }

    public setReplaceExisting(replaceExisting: boolean): void {
        this.settingsService.update({ replaceExisting });
    }

    public setImportLabels(importLabels: boolean): void {
        this.settingsService.update({ importLabels });
    }

    public resetDefaults(): void {
        this.settingsService.reset();
    }

    public close(): void {
        this.closed.emit();
    }
}
