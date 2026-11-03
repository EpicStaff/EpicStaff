import { A11yModule } from '@angular/cdk/a11y';
import { OverlayModule } from '@angular/cdk/overlay';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    HostListener,
    inject,
    Injector,
    input,
    output,
    signal,
    viewChildren,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { nextListIndex } from '@shared/utils';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { FLOW_ACTION_PERMISSIONS } from '../../core/constants/flow-action-permissions';
import { KeymapService } from '../../services/keymap.service';

@Component({
    selector: 'app-flow-export-import-button',
    imports: [A11yModule, OverlayModule, AppSvgIconComponent, MatTooltipModule, HasPermissionDirective],
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

    private readonly menuItems = viewChildren<ElementRef<HTMLButtonElement>>('menuItem');

    protected isOpen = signal(false);

    readonly canUseMenu = computed(() => this.permissions.meets(FLOW_ACTION_PERMISSIONS.exportImport));

    private readonly permissions = inject(PermissionsService);
    protected readonly keymap = inject(KeymapService);
    private readonly host: HTMLElement = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
    private readonly injector = inject(Injector);

    @HostListener('mousedown', ['$event'])
    onMouseDown(event: MouseEvent): void {
        event.stopPropagation();
    }

    /** Opens or closes the menu like a click on the button; an opened menu gets the keyboard focus. */
    toggleMenuFromKeyboard(): void {
        if (this.isOpen()) {
            this.close();
            return;
        }
        // The toolbar hides this button when it runs out of room (the node side panel is open); a menu anchored
        // to a hidden button would open in the corner of the screen, so the key does nothing until it is back.
        if (getComputedStyle(this.host).display === 'none') return;
        this.open();
    }

    /** Escape closes the menu and goes no further, unless something inside it already used this Escape. */
    protected onMenuEscape(event: Event): void {
        if (event.defaultPrevented) return;
        event.stopPropagation();
        this.close();
    }

    /** Arrow keys move between the items, Home and End jump to the ends; Enter clicks the focused item button. */
    protected onMenuKeydown(event: KeyboardEvent): void {
        const items = this.menuItems().map((item) => item.nativeElement);
        const current = items.indexOf(event.target as HTMLButtonElement);
        const next = nextListIndex(event.key, current, items.length);
        if (next === null) return;
        event.preventDefault();
        items[next].focus();
    }

    protected toggle(event: Event): void {
        event.stopPropagation();
        if (this.isOpen()) {
            this.close();
        } else {
            this.open();
        }
    }

    /** The first item takes the focus once the menu is drawn; the menu's focus trap gives it back on close. */
    private open(): void {
        this.isOpen.set(true);
        afterNextRender(() => this.menuItems()[0]?.nativeElement.focus(), { injector: this.injector });
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

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
