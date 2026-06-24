import { CdkOverlayOrigin, OverlayModule } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, EventEmitter, inject, Input, Output } from '@angular/core';

import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { ImportFlowSettingsService } from '../../services/import-flow-settings.service';

@Component({
    selector: 'app-import-flow-options-popover',
    standalone: true,
    imports: [OverlayModule, HelpTooltipComponent],
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

    public togglePreserveUuids(): void {
        const newValue = !this.settings().preserveUuids;
        this.settingsService.update({
            preserveUuids: newValue,
            ...(newValue === false && { replaceExisting: false }),
        });
    }

    public toggleReplaceExisting(): void {
        this.settingsService.update({ replaceExisting: !this.settings().replaceExisting });
    }

    public toggleImportLabels(): void {
        this.settingsService.update({ importLabels: !this.settings().importLabels });
    }

    public resetDefaults(): void {
        this.settingsService.reset();
    }

    public close(): void {
        this.closed.emit();
    }
}
