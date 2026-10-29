import { NgComponentOutlet, NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    output,
    Signal,
    signal,
    TemplateRef,
    viewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, AuthorshipDetailsDialogService } from '@shared/components';
import { NodeType } from '@shared/models';

import { ToastService } from '../../../../services/notifications';
import { NODE_DIFF_BADGES } from '../../../core/constants/node-diff-badges';
import { COMPACT_HEADER_NODE_TYPES, PANEL_COMPONENT_MAP } from '../../../core/enums/node-panel.map';
import { hasNodeDetails } from '../../../core/helpers/node-details.util';
import { showsNodeNumber } from '../../../core/helpers/node-number.util';
import { NodeModel } from '../../../core/models/node.model';
import { NodePanel } from '../../../core/models/node-panel.interface';
import { NODE_PANEL_DIFF, NodePanelDiff } from '../../../core/providers/node-panel-diff.token';
import { FlowDiffStateService } from '../../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { KeymapService } from '../../../services/keymap.service';
import { NodeAuthorshipStore } from '../../../services/node-authorship.store';
import { SidePanelService } from '../../../services/side-panel.service';

const INVALID_FIELDS_NOT_SAVED_MESSAGE = "Changes weren't saved — this node has invalid fields.";

/** What the shell reads from the open panel (the component the outlet rendered). */
interface PanelInstanceView {
    /** The node the panel edits. */
    node?: Signal<NodeModel>;
    isDirty?: Signal<boolean>;
    /** Opt-in: the node must be saved to the backend although the panel has no edit (Save shows then too). */
    needsSave?: Signal<boolean>;
    isSaving?: Signal<boolean>;
    form?: { invalid: boolean };
    onSaveClick?: () => void;
    headerActionsTemplate?: () => TemplateRef<unknown> | undefined;
}

@Component({
    selector: 'app-node-panel-shell',
    imports: [NgComponentOutlet, NgTemplateOutlet, AppSvgIconComponent, MatTooltipModule],
    template: `
        @if (node() && panelComponent()) {
            <aside
                #panel
                class="node-panel"
                [class.shake-attention]="isShaking()"
                [class.expanded]="isExpanded()"
            >
                <header
                    class="dialog-header"
                    [class.dialog-header--compact]="isCompactHeader()"
                >
                    <div class="icon-and-title">
                        <i
                            [class]="node()!.icon"
                            [style.color]="node()!.color || '#685fff'"
                        ></i>
                        <span class="title-with-number">
                            <span class="title">{{ nodeNameToDisplay() }}</span>
                            @if (nodeNumberToDisplay(); as nodeNumber) {
                                <span class="node-number">#{{ nodeNumber }}</span>
                            }
                        </span>
                    </div>
                    <div class="header-actions">
                        <!-- The compact header shows the details button first, before the panel's own actions. -->
                        @if (isCompactHeader()) {
                            <ng-container [ngTemplateOutlet]="detailsButtonTpl"></ng-container>
                        }
                        @if (panelInstanceSig()?.headerActionsTemplate?.()) {
                            <ng-container
                                [ngTemplateOutlet]="panelInstanceSig()!.headerActionsTemplate!()!"
                            ></ng-container>
                        }
                        @if (showSaveButton()) {
                            <button
                                class="save-btn"
                                [class.save-btn--icon-only]="!isExpanded()"
                                type="button"
                                matTooltip="Save local node changes"
                                matTooltipPosition="below"
                                [disabled]="panelInstanceSig()?.form?.invalid || panelInstanceSig()?.isSaving()"
                                (click)="onHeaderSaveClick()"
                            >
                                <app-svg-icon
                                    icon="floppy"
                                    size="1.25rem"
                                ></app-svg-icon>
                                <span class="btn-label">Save</span>
                            </button>
                        }
                        @if (!isCompactHeader()) {
                            <ng-container [ngTemplateOutlet]="detailsButtonTpl"></ng-container>
                        }
                        @if (shouldShowExpandButton()) {
                            <button
                                class="expand-btn"
                                aria-label="Toggle panel size"
                                [matTooltip]="isExpanded() ? 'Minimize panel' : 'Expand panel'"
                                matTooltipPosition="below"
                                (click)="toggleExpanded()"
                            >
                                <app-svg-icon
                                    [icon]="isExpanded() ? 'arrows-minimize' : 'arrows-maximize'"
                                    size="1.25rem"
                                ></app-svg-icon>
                            </button>
                        }
                        <div class="close-action">
                            <span class="esc-label">ESC</span>
                            <button
                                class="close-btn"
                                aria-label="Close dialog"
                                matTooltip="Close"
                                matTooltipPosition="below"
                                (click)="onCloseClick()"
                            >
                                <app-svg-icon
                                    icon="x"
                                    [size]="isCompactHeader() ? '1.25rem' : '24px'"
                                ></app-svg-icon>
                            </button>
                        </div>
                    </div>
                </header>

                <ng-template #detailsButtonTpl>
                    @if (showDetailsButton()) {
                        <button
                            #detailsButton
                            class="details-btn"
                            type="button"
                            aria-label="Node details"
                            matTooltip="Node details"
                            matTooltipPosition="below"
                            (click)="openNodeDetails(detailsButton)"
                        >
                            <app-svg-icon
                                icon="alert-circle"
                                [size]="isCompactHeader() ? '1rem' : '1.25rem'"
                            ></app-svg-icon>
                        </button>
                    }
                </ng-template>

                <!-- Changes tab of a version preview: what a restore does to an added or removed node. -->
                @if (diffBanner(); as banner) {
                    <div
                        class="diff-banner diff-banner--{{ banner.status }}"
                        role="status"
                    >
                        <span class="diff-banner__icon">
                            <i
                                [class]="banner.icon"
                                aria-hidden="true"
                            ></i>
                        </span>
                        <span class="diff-banner__text">{{ banner.text }}</span>
                    </div>
                }

                <main>
                    <ng-container
                        [ngComponentOutlet]="panelComponent()"
                        [ngComponentOutletInputs]="componentInputs()"
                        [ngComponentOutletInjector]="outletInjector"
                        #outlet="ngComponentOutlet"
                    ></ng-container>
                </main>
            </aside>
        }
    `,
    styleUrls: ['./node-panel-shell.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NodePanelShellComponent {
    public readonly node = input<NodeModel | null>(null);
    public readonly currentFlowId = input<number | null>(null);
    public readonly save = output<NodeModel>();
    public readonly autosave = output<NodeModel>();

    public readonly panelComponent = computed(() => {
        const node = this.node();
        if (!node) return null;

        return PANEL_COMPONENT_MAP[node.type] || null;
    });

    public readonly nodeNameToDisplay = computed(() => {
        const n = this.node();
        if (!n) return '';
        if (n.node_name === '__start__') return 'Start';
        if (n.type === 'end' || n.node_name === '__end_node__') return 'End';
        return n.node_name ?? '';
    });

    /** The #N shown next to the name, styled like the number under a canvas node's name; none while the node has no name. */
    protected readonly nodeNumberToDisplay = computed(() => {
        const n = this.node();
        if (!n || !this.nodeNameToDisplay() || !showsNodeNumber(n)) return null;
        return n.nodeNumber;
    });

    public readonly shouldShowExpandButton = computed(() => {
        const node = this.node();
        return (
            node &&
            node.type !== 'table' &&
            node.type !== NodeType.SCHEDULE_TRIGGER &&
            node.type !== NodeType.KEY_VALUE &&
            node.type !== 'classification-decision-table'
        );
    });

    /** The open panel's header content is a 28px row (see COMPACT_HEADER_NODE_TYPES). */
    protected readonly isCompactHeader = computed(() => {
        const node = this.node();
        return !!node && COMPACT_HEADER_NODE_TYPES.has(node.type);
    });

    /** Viewing details needs only flow read access, so read-only and preview modes show it too. */
    protected readonly showDetailsButton = computed(() => {
        const node = this.node();
        return !!node && hasNodeDetails(node.type);
    });

    protected readonly outlet = viewChild(NgComponentOutlet);
    private readonly panel = viewChild<ElementRef<HTMLElement>>('panel');
    protected readonly componentInputs = computed(() => {
        const node = this.node();

        return {
            node,
            isExpanded: this.isExpanded(),
            graphId: this.currentFlowId(),
            ...(node?.type === 'subgraph' ? { currentFlowId: this.currentFlowId() } : {}),
        };
    });

    /** The open node's diff on the Changes tab of a version preview; `null` elsewhere. */
    private readonly panelDiff = computed<NodePanelDiff | null>(() => {
        const node = this.node();
        return node ? this.flowDiffState.nodeDiff(node.id) : null;
    });
    /** Changed and unchanged nodes get no banner: only a node a restore adds or removes as a whole. */
    protected readonly diffBanner = computed(() => {
        const status = this.panelDiff()?.status;
        if (status !== 'added' && status !== 'deleted') return null;
        const badge = NODE_DIFF_BADGES[status];
        return { status, icon: badge.icon, text: `${badge.label}.` };
    });
    /** Gives the panel, and the notes inside it, the open node's diff without a new input on every panel. */
    protected readonly outletInjector = Injector.create({
        providers: [{ provide: NODE_PANEL_DIFF, useValue: this.panelDiff }],
        parent: inject(Injector),
    });

    protected readonly isShaking = signal(false);
    protected readonly isExpanded = signal(false);
    private panelInstance:
        | (NodePanel & {
              onSaveSilently?: () => NodeModel | null;
              captureForValidation?: () => NodeModel | null;
              hasEditsLeftOut?: () => boolean;
          })
        | null = null;
    protected readonly panelInstanceSig = signal<PanelInstanceView | null>(null);
    /**
     * The type of the node the open panel edits. Not always `node()`: on a switch to another node, `node()`
     * is already the next one while the panel (autosaved then) still holds the previous one.
     */
    private readonly panelNodeType = computed<NodeType | null>(
        () => this.panelInstanceSig()?.node?.().type ?? this.node()?.type ?? null
    );
    /** The open panel's node may not be changed: a read-only editor, or a trigger node without Flows:Use. */
    public readonly isNodeReadOnly = computed(() => {
        const nodeType = this.panelNodeType();
        return nodeType ? this.flowReadOnly.isNodeTypeReadOnly(nodeType) : this.flowReadOnly.isReadOnly();
    });
    protected readonly showSaveButton = computed(() => {
        if (this.isNodeReadOnly()) return false;
        const panel = this.panelInstanceSig();
        const hasSomethingToSave = (panel?.isDirty?.() ?? false) || (panel?.needsSave?.() ?? false);
        return hasSomethingToSave && !!panel?.onSaveClick;
    });
    private previousNodeId: string | null = null;
    private isUpdatingNode = false;
    private isAutosaving = false;
    private lastHandledAutosaveTrigger = 0;
    private autosavePending = false;
    private readonly sidePanelService = inject(SidePanelService);
    private readonly toastService = inject(ToastService);
    private readonly flowReadOnly = inject(FlowReadOnlyService);
    private readonly flowDiffState = inject(FlowDiffStateService);
    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);
    private readonly nodeAuthorshipStore = inject(NodeAuthorshipStore);
    private readonly keymap = inject(KeymapService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        this.keymap.register('editing.escape', () => this.onEscape(), {
            allowInEditable: true,
            destroyRef: this.destroyRef,
        });
        this.keymap.register('editing.save', () => this.onShortcutSave(), { destroyRef: this.destroyRef });

        effect(() => {
            const trigger = this.sidePanelService.autosaveTrigger();
            this.tryAutosave(trigger);
        });

        effect(() => {
            const node = this.node();
            if (node) {
                if (this.previousNodeId !== node.id) {
                    this.isExpanded.set(false);
                }

                // Auto-expand for decision table nodes
                if (node.type === 'table' || node.type === 'classification-decision-table') {
                    this.isExpanded.set(true);
                }

                if (
                    this.previousNodeId &&
                    this.previousNodeId !== node.id &&
                    this.panelInstance &&
                    !this.isUpdatingNode &&
                    !this.isAutosaving
                ) {
                    this.isUpdatingNode = true;
                    this.performAutosave();
                }

                setTimeout(() => {
                    const outletRef = this.outlet();
                    if (outletRef?.componentInstance) {
                        this.panelInstance = outletRef.componentInstance as NodePanel & {
                            onSaveSilently?: () => NodeModel | null;
                        };
                        this.panelInstanceSig.set(outletRef.componentInstance as PanelInstanceView);
                        this.previousNodeId = node.id;
                        this.isUpdatingNode = false;
                    }
                }, 0);
            } else {
                // Reset when no node is selected
                this.panelInstance = null;
                this.panelInstanceSig.set(null);
                this.previousNodeId = null;
                this.isUpdatingNode = false;
                this.isAutosaving = false;
            }
        });

        effect(() => {
            const shouldExpand = this.sidePanelService.expandRequest();
            if (shouldExpand) {
                this.isExpanded.set(true);
                this.sidePanelService.clearExpandRequest();
            }
        });
    }

    protected onHeaderSaveClick(): void {
        this.panelInstanceSig()?.onSaveClick?.();
    }

    protected openNodeDetails(trigger: HTMLElement): void {
        const node = this.node();
        if (!node) return;
        // Read at click time, so the dialog shows what the latest graph response said.
        this.authorshipDetailsDialog.open('Node Details', this.nodeAuthorshipStore.authorshipOf(node), trigger);
    }

    protected onCloseClick(): void {
        this.saveSidePanel();
    }

    protected onEscape(): void {
        this.saveSidePanel();
    }

    protected toggleExpanded(): void {
        this.isExpanded.update((expanded) => !expanded);
    }

    protected onShortcutSave(): void {
        const nodeType = this.panelNodeType();
        if (this.isNodeReadOnly()) {
            if (nodeType) {
                this.flowReadOnly.notifyNodeTypeBlocked(nodeType);
            } else {
                this.flowReadOnly.notifyBlocked();
            }
            return;
        }
        if (!this.panelInstance || typeof this.panelInstance.onSaveSilently !== 'function') {
            return;
        }
        const updatedNode = this.panelInstance.onSaveSilently();
        if (!updatedNode) {
            return;
        }
        this.save.emit(updatedNode);
    }

    public expandPanel(): void {
        if (!this.shouldShowExpandButton()) return;
        this.isExpanded.set(true);
    }

    private saveSidePanel(): void {
        if (this.isNodeReadOnly()) {
            this.sidePanelService.clearSelection();
            return;
        }
        if (
            this.panelInstance &&
            typeof this.panelInstance.onSave === 'function' &&
            (this.panelInstanceSig()?.isDirty?.() ?? true)
        ) {
            const updatedNode = this.panelInstance.onSave();
            if (updatedNode) {
                this.save.emit(updatedNode);
                return;
            }
            // An invalid test payload is the user's to fix and the last saved one is kept: a warning, not a failure.
            if (this.panelInstance.hasEditsLeftOut?.()) {
                this.toastService.warning(INVALID_FIELDS_NOT_SAVED_MESSAGE);
            } else {
                this.toastService.error(INVALID_FIELDS_NOT_SAVED_MESSAGE);
            }
        }
        this.sidePanelService.clearSelection();
    }

    private tryAutosave(trigger: number): void {
        if (trigger === this.lastHandledAutosaveTrigger || !this.panelInstance) {
            return;
        }
        if (this.isNodeReadOnly()) {
            this.lastHandledAutosaveTrigger = trigger;
            return;
        }
        if (this.isAutosaving) {
            this.autosavePending = true;
            return;
        }

        this.lastHandledAutosaveTrigger = trigger;
        this.isAutosaving = true;
        this.performAutosave();
        setTimeout(() => {
            this.isAutosaving = false;
            if (this.autosavePending) {
                this.autosavePending = false;
                this.tryAutosave(this.sidePanelService.autosaveTrigger());
            }
        }, 100);
    }

    private performAutosave(): void {
        if (this.isNodeReadOnly()) return;
        if (
            this.panelInstance &&
            typeof this.panelInstance.onSave === 'function' &&
            (this.panelInstanceSig()?.isDirty?.() ?? true)
        ) {
            const updatedNode = this.panelInstance.onSave();
            if (updatedNode) {
                this.autosave.emit(updatedNode);
            }
        }
    }

    public captureCurrentNodeState(): NodeModel | null {
        if (!this.panelInstance) {
            return null;
        }
        if (typeof this.panelInstance.onSaveSilently === 'function') {
            try {
                return this.panelInstance.onSaveSilently();
            } catch (error) {
                console.error('Failed to capture node panel state silently', error);
            }
        }
        // Fall back to onSave() which is required by the NodePanel interface
        try {
            return this.panelInstance.onSave();
        } catch (error) {
            console.error('Failed to capture node panel state via onSave', error);
            return null;
        }
    }

    /** Where the open panel starts on screen (viewport x), or null while it is closed; the canvas left of it stays visible. */
    public panelLeftEdge(): number | null {
        return this.panel()?.nativeElement.getBoundingClientRect().left ?? null;
    }

    public hasPanelInstance(): boolean {
        return this.panelInstance !== null;
    }

    /**
     * Captures the open panel's current node state for a flow-wide save, even when the
     * panel's own form is invalid. Prefers `captureForValidation()` (which always returns the
     * in-progress node and marks fields touched so invalid ones highlight) over
     * `captureCurrentNodeState()` (which can return `null` and hide the edit entirely from a
     * flow-wide save when the form is invalid).
     */
    public captureCurrentNodeStateForSave(): NodeModel | null {
        if (!this.panelInstance) {
            return null;
        }
        if (typeof this.panelInstance.captureForValidation === 'function') {
            try {
                return this.panelInstance.captureForValidation();
            } catch (error) {
                console.error('Failed to capture node panel state for validation', error);
            }
        }
        return this.captureCurrentNodeState();
    }
}
