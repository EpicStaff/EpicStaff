import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { Component, ElementRef, output, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

/** The ⋮ button and its "View Details" menu of the LLM, embedding and voice config cards in the LLM Library. */
@Component({
    selector: 'app-config-card-more-menu',
    imports: [MatTooltipModule, CdkMenuTrigger, CdkMenu, CdkMenuItem],
    templateUrl: './config-card-more-menu.component.html',
    styleUrls: ['./config-card-more-menu.component.scss'],
})
export class ConfigCardMoreMenuComponent {
    /** "View Details" was chosen; carries the ⋮ button the details dialog should close back to. */
    public readonly viewDetailsClick = output<HTMLElement>();

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

    /**
     * The menu item closes the menu itself once this returns, focusing the trigger — so focus stays on
     * the card even when the host opens nothing. The host's details dialog, though, has already
     * recorded the focused menu item by then, which is why the trigger travels with the event.
     */
    protected onViewDetails(): void {
        this.viewDetailsClick.emit(this.menuTriggerButton().nativeElement);
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
