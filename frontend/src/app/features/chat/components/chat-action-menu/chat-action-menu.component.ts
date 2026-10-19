import { A11yModule } from '@angular/cdk/a11y';
import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { Component, ElementRef, input, output, signal, viewChild } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

/** `Id`: the menu's own union of action ids, so a handler for an id the menu never offers does not compile. */
export interface ChatActionMenuItem<Id extends string = string> {
    /** What `chosen` emits. */
    id: Id;
    label: string;
    disabled?: boolean;
}

// Under the button, flush with its end: the button sits at the end of a bar.
const BELOW_END: ConnectedPosition[] = [
    { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
];

/**
 * A ⋯ button and the actions it opens, drawn like the row ⋯ menus. The focus moves into the open menu and back to the
 * button when it closes. Choosing an item puts the focus back on the button before the action runs, so a dialog the
 * action opens returns the focus there too.
 */
@Component({
    selector: 'app-chat-action-menu',
    imports: [A11yModule, OverlayModule, AppSvgIconComponent],
    templateUrl: './chat-action-menu.component.html',
    styleUrl: './chat-action-menu.component.scss',
})
export class ChatActionMenuComponent<Id extends string = string> {
    readonly items = input.required<readonly ChatActionMenuItem<Id>[]>();
    /** The button's accessible name, e.g. "Conversation actions". */
    readonly label = input.required<string>();
    readonly icon = input('dots-vertical');
    readonly chosen = output<Id>();

    private readonly trigger = viewChild.required<ElementRef<HTMLButtonElement>>('trigger');

    protected readonly isOpen = signal(false);

    protected readonly positions = BELOW_END;

    protected toggle(): void {
        this.isOpen.update((isOpen) => !isOpen);
    }

    protected close(): void {
        this.isOpen.set(false);
    }

    protected choose(item: ChatActionMenuItem<Id>): void {
        this.isOpen.set(false);
        this.trigger().nativeElement.focus();
        this.chosen.emit(item.id);
    }
}
