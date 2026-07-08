import { OverlayModule } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, HostListener, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-flow-export-import-button',
    standalone: true,
    imports: [OverlayModule, AppSvgIconComponent, MatTooltipModule],
    templateUrl: './flow-export-import-button.component.html',
    styleUrls: ['./flow-export-import-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowExportImportButtonComponent {
    selectedCount = input<number>(0);
    allSelectedAreCdt = input<boolean>(false);

    exportSelectedJson = output<void>();
    exportSelectedCsv = output<void>();
    exportJson = output<void>();
    exportCsv = output<void>();
    import = output<void>();

    protected isOpen = signal(false);

    @HostListener('mousedown', ['$event'])
    onMouseDown(event: MouseEvent): void {
        event.stopPropagation();
    }

    protected toggle(event: Event): void {
        event.stopPropagation();
        this.isOpen.update((v) => !v);
    }

    protected close(): void {
        this.isOpen.set(false);
    }

    protected onExportSelectedJson(): void {
        this.close();
        this.exportSelectedJson.emit();
    }

    protected onExportSelectedCsv(): void {
        this.close();
        this.exportSelectedCsv.emit();
    }

    protected onExportJson(): void {
        this.close();
        this.exportJson.emit();
    }

    protected onExportCsv(): void {
        this.close();
        this.exportCsv.emit();
    }

    protected onImport(): void {
        this.close();
        this.import.emit();
    }
}
