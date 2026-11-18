import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import {
    afterNextRender,
    Component,
    computed,
    ElementRef,
    inject,
    Injector,
    input,
    output,
    viewChild,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

type FocusTarget = 'start' | 'cancel';

/**
 * The bulk export control of the collections list, a split button.
 * - Outside select mode: Export (enters select mode) | ⌄ (a menu: Select, Select all).
 * - In select mode: the selected count (opens the same menu) | ✕ (leaves select mode) | ✓ (exports the selection;
 *   inert while nothing is selected).
 *
 * The host owns select mode and the selection; this only shows them and reports what the user asked for. The
 * segments swap with the mode, so the focus moves to the segment now in the place of the one that went.
 */
@Component({
    selector: 'app-collections-export-control',
    imports: [CdkMenuTrigger, CdkMenu, CdkMenuItem, AppSvgIconComponent, MatTooltip],
    templateUrl: './collections-export-control.component.html',
    styleUrls: ['./collections-export-control.component.scss'],
})
export class CollectionsExportControlComponent {
    readonly selectMode = input(false);
    readonly selectedCount = input(0);
    /** Every collection the list shows is selected; the menu then offers "Deselect all". */
    readonly allSelected = input(false);

    readonly selectModeEntered = output<void>();
    readonly selectAllToggled = output<void>();
    readonly cleared = output<void>();
    readonly exportConfirmed = output<void>();

    private readonly startButton = viewChild<ElementRef<HTMLButtonElement>>('startButton');
    private readonly cancelButton = viewChild<ElementRef<HTMLButtonElement>>('cancelButton');

    protected readonly canExport = computed(() => this.selectedCount() > 0);
    protected readonly selectAllLabel = computed(() => (this.allSelected() ? 'Deselect all' : 'Select all'));
    protected readonly confirmTooltip = computed(() =>
        this.canExport() ? 'Export selected' : 'Select collections to export'
    );

    // 8px below the control, right edges aligned: the control sits at the sidebar's right edge.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 8 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -8 },
    ];

    private readonly injector = inject(Injector);

    protected enterSelectMode(): void {
        this.selectModeEntered.emit();
        this.focusAfterRender('cancel');
    }

    protected toggleSelectAll(): void {
        if (!this.selectMode()) this.enterSelectMode();
        this.selectAllToggled.emit();
    }

    protected clear(): void {
        this.cleared.emit();
        this.focusAfterRender('start');
    }

    protected confirmExport(): void {
        if (!this.canExport()) return;
        this.exportConfirmed.emit();
        this.focusAfterRender('start');
    }

    private focusAfterRender(target: FocusTarget): void {
        afterNextRender(
            () => {
                const button = target === 'start' ? this.startButton() : this.cancelButton();
                button?.nativeElement.focus();
            },
            { injector: this.injector }
        );
    }
}
