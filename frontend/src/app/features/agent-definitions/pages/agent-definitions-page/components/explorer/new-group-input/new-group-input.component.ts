import { HttpErrorResponse } from '@angular/common/http';
import {
    afterRenderEffect,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    inject,
    signal,
    viewChild,
} from '@angular/core';
import { extractHttpErrorMessage } from '@shared/utils';

import { AgentsPageStore } from '../../../../../services/agents-page-store.service';

/** The inline "new group" input of a grouped section; the store's draft says which section shows it. */
@Component({
    selector: 'app-new-group-input',
    templateUrl: './new-group-input.component.html',
    styleUrls: ['./new-group-input.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NewGroupInputComponent {
    private readonly newGroupInput = viewChild<ElementRef<HTMLInputElement>>('newGroupInput');

    protected readonly newGroupError = signal<string | null>(null);
    protected readonly creatingGroup = signal<boolean>(false);

    private readonly focusNewGroupInput = afterRenderEffect(() => this.newGroupInput()?.nativeElement.focus());

    protected readonly store: AgentsPageStore = inject(AgentsPageStore);

    protected createGroup(name: string, refocusOnError = true): void {
        const draft = this.store.newGroupDraft();
        if (!draft || this.creatingGroup()) return;
        if (!name.trim()) {
            this.cancelNewGroup();
            return;
        }
        this.creatingGroup.set(true);
        this.store.createGroup(name, draft.assign).subscribe({
            next: () => {
                this.creatingGroup.set(false);
                this.cancelNewGroup();
            },
            error: (err: HttpErrorResponse) => {
                this.creatingGroup.set(false);
                this.newGroupError.set(extractHttpErrorMessage(err, 'Failed to create group'));
                // Disabling the input dropped its focus; give it back so the name can be fixed.
                // Not after a blur save: the user has moved on, and stealing focus back would trap them.
                if (refocusOnError) setTimeout(() => this.newGroupInput()?.nativeElement.focus());
            },
        });
    }

    protected cancelNewGroup(): void {
        this.newGroupError.set(null);
        this.store.cancelNewGroup();
    }

    /**
     * Leaving the input saves a typed name and cancels an empty one. While an error is
     * shown the draft stays as is, so blur never resubmits a name the server just rejected.
     */
    protected onNewGroupBlur(name: string): void {
        if (this.creatingGroup() || this.newGroupError()) return;
        if (!name.trim()) {
            this.cancelNewGroup();
            return;
        }
        this.createGroup(name, false);
    }
}
