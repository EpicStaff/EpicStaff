import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    effect,
    ElementRef,
    inject,
    linkedSignal,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { FetchErrorStateComponent, LabelColorPickerComponent } from '@shared/components';
import { LabelColor, labelColorInTurn } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';

import { BranchTreeNode, nodeKey } from '../../../../../models/tree-node.model';
import { AgentsPageStore } from '../../../../../services/agents-page-store.service';
import { ExplorerGroupBlockComponent } from '../group-block/group-block.component';
import {
    ExplorerTreeAttachSurfaceEvent,
    ExplorerTreeMenuEvent,
    ExplorerTreeMenuOpenEvent,
    TreeNodeComponent,
} from '../tree-node/tree-node.component';

@Component({
    selector: 'app-agents-section',
    imports: [TreeNodeComponent, FetchErrorStateComponent, ExplorerGroupBlockComponent, LabelColorPickerComponent],
    templateUrl: './agents-section.component.html',
    styleUrls: ['./agents-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentsSectionComponent {
    selectNode = output<BranchTreeNode>();
    menuAction = output<ExplorerTreeMenuEvent>();
    menuOpen = output<ExplorerTreeMenuOpenEvent>();
    attachSurface = output<ExplorerTreeAttachSurfaceEvent>();

    private readonly newGroupInput = viewChild<ElementRef<HTMLInputElement>>('newGroupInput');

    protected readonly newGroupError = signal<string | null>(null);
    protected readonly creatingGroup = signal<boolean>(false);

    private readonly focusNewGroupInput = effect(() => this.newGroupInput()?.nativeElement.focus());

    readonly trackByKey = (_: number, n: BranchTreeNode) => nodeKey(n);

    protected readonly store: AgentsPageStore = inject(AgentsPageStore);

    /** Each new draft suggests the next color in turn; the picker can change it. */
    protected readonly newGroupColor = linkedSignal<LabelColor>(() => {
        this.store.newGroupDraft();
        return labelColorInTurn(this.store.groups().length);
    });

    onSelect(node: BranchTreeNode): void {
        this.selectNode.emit(node);
    }

    onMenuAction(event: ExplorerTreeMenuEvent): void {
        this.menuAction.emit(event);
    }

    onMenuOpen(event: ExplorerTreeMenuOpenEvent): void {
        this.menuOpen.emit(event);
    }

    onAttachSurface(event: ExplorerTreeAttachSurfaceEvent): void {
        this.attachSurface.emit(event);
    }

    protected createGroup(name: string, refocusOnError = true): void {
        const draft = this.store.newGroupDraft();
        if (!draft || this.creatingGroup()) return;
        if (!name.trim()) {
            this.cancelNewGroup();
            return;
        }
        this.creatingGroup.set(true);
        this.store.createGroup(name, draft.assign, this.newGroupColor()).subscribe({
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

    /**
     * Focus moving to the color picker (its trigger, or its options in the overlay) is still
     * editing the draft, so only leaving for anything else counts as leaving the field.
     */
    protected onNewGroupFocusOut(event: FocusEvent, name: string): void {
        const next = event.relatedTarget as HTMLElement | null;
        const field = event.currentTarget as HTMLElement;
        if (next && (field.contains(next) || next.closest('.cdk-overlay-container'))) return;
        this.onNewGroupBlur(name);
    }

    /** Picking a color hands focus back to the name, so Enter and leaving the field work as before. */
    protected onNewGroupColor(color: LabelColor): void {
        this.newGroupColor.set(color);
        this.newGroupInput()?.nativeElement.focus();
    }

    /**
     * Leaving the input saves a typed name and cancels an empty one. While an error is
     * shown the draft stays as is, so blur never resubmits a name the server just rejected.
     */
    private onNewGroupBlur(name: string): void {
        if (this.creatingGroup() || this.newGroupError()) return;
        if (!name.trim()) {
            this.cancelNewGroup();
            return;
        }
        this.createGroup(name, false);
    }

    protected cancelNewGroup(): void {
        this.newGroupError.set(null);
        this.store.cancelNewGroup();
    }
}
