import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, ElementRef, input, output, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, LlmLibraryModel, ResourceCode } from '@shared/models';

/** "View Details" was chosen on a card; `trigger` is the ⋮ button the details dialog should close back to. */
export interface LlmLibraryCardViewDetailsEvent {
    model: LlmLibraryModel;
    trigger: HTMLElement;
}

@Component({
    selector: 'app-llm-library-card',
    imports: [MatTooltipModule, HasPermissionDirective, AppSvgIconComponent, CdkMenuTrigger, CdkMenu, CdkMenuItem],
    templateUrl: './llm-library-card.component.html',
    styleUrls: ['./llm-library-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmLibraryCardComponent {
    public readonly model = input.required<LlmLibraryModel>();

    public readonly editClick = output<LlmLibraryModel>();
    public readonly deleteClick = output<LlmLibraryModel>();
    public readonly viewDetailsClick = output<LlmLibraryCardViewDetailsEvent>();

    private readonly menuTrigger = viewChild.required(CdkMenuTrigger);
    private readonly menuTriggerButton = viewChild.required<CdkMenuTrigger, ElementRef<HTMLButtonElement>>(
        CdkMenuTrigger,
        { read: ElementRef }
    );

    // Below the trigger, right edges aligned; flips above when there is no room.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    protected onEdit(): void {
        this.editClick.emit(this.model());
    }

    protected onDelete(): void {
        this.deleteClick.emit(this.model());
    }

    /**
     * The menu item closes the menu itself once this returns, focusing the trigger — so focus stays on
     * the card even when the host opens nothing. The host's details dialog, though, has already
     * recorded the focused menu item by then, which is why the trigger travels with the event.
     */
    protected onViewDetails(): void {
        this.viewDetailsClick.emit({ model: this.model(), trigger: this.menuTriggerButton().nativeElement });
    }

    /**
     * Escape must close only the menu. CdkMenu does close itself on Escape, but lets the event
     * bubble on to the overlay keyboard dispatcher, which hands it to the next overlay down — the
     * Configure Models dialog — and closes that too. Stopping it on the menu element is too late:
     * CdkMenu destroys the menu view (and its listeners) first. So the focused item intercepts
     * Escape before CdkMenu sees it and closes the menu the same way CdkMenu would.
     */
    protected onMenuItemEscape(event: Event): void {
        event.stopPropagation();
        this.closeMenuToTrigger();
    }

    private closeMenuToTrigger(): void {
        this.menuTrigger().close();
        this.menuTriggerButton().nativeElement.focus();
    }
}
