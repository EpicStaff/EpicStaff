import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, ElementRef, input, output, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, LlmLibraryModel, ResourceCode } from '@shared/models';

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
    public readonly viewDetailsClick = output<LlmLibraryModel>();

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

    protected onViewDetails(): void {
        // Return focus to the trigger *before* the host opens the details dialog: a CDK dialog
        // restores focus on close to whatever was focused when it opened, and the menu item is
        // destroyed with the menu, so focus would otherwise fall to <body> — outside the
        // Configure Models dialog.
        this.closeMenuToTrigger();
        this.viewDetailsClick.emit(this.model());
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
