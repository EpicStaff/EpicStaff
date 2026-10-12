import { A11yModule } from '@angular/cdk/a11y';
import { OverlayModule } from '@angular/cdk/overlay';
import { Component, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { ChatBinding } from '../../models/chat.model';
import { ChatBindingStatusComponent } from '../chat-binding-status/chat-binding-status.component';

export type ChatBindingCardAction = 'settings' | 'pause' | 'resume' | 'snippet' | 'delete';

/** One binding on the bindings list: opens its workspace, and its ⋮ menu offers the binding's actions. */
@Component({
    selector: 'app-chat-binding-card',
    imports: [
        A11yModule,
        OverlayModule,
        MatTooltipModule,
        RouterLink,
        AppSvgIconComponent,
        HasPermissionDirective,
        ChatBindingStatusComponent,
    ],
    templateUrl: './chat-binding-card.component.html',
    styleUrls: ['./chat-binding-card.component.scss'],
})
export class ChatBindingCardComponent {
    readonly binding = input.required<ChatBinding>();
    // Null while the flows list loads or when the flow is gone.
    readonly flowName = input<string | null>(null);
    readonly waiting = input(0);
    readonly action = output<ChatBindingCardAction>();

    readonly isMenuOpen = signal(false);

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;

    toggleMenu(): void {
        this.isMenuOpen.update((open) => !open);
    }

    closeMenu(): void {
        this.isMenuOpen.set(false);
    }

    choose(action: ChatBindingCardAction): void {
        this.closeMenu();
        this.action.emit(action);
    }
}
