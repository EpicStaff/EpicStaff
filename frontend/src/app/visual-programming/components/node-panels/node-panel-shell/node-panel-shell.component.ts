import { NgComponentOutlet, NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    input,
    output,
    Signal,
    signal,
    TemplateRef,
    viewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ToastService } from '../../../../services/notifications';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ShortcutListenerDirective } from '../../../core/directives/shortcut-listener.directive';
import { PANEL_COMPONENT_MAP } from '../../../core/enums/node-panel.map';
import { NodeType } from '../../../core/enums/node-type';
import { NodeModel } from '../../../core/models/node.model';
import { NodePanel } from '../../../core/models/node-panel.interface';
import { SidePanelService } from '../../../services/side-panel.service';

@Component({
    standalone: true,
    selector: 'app-node-panel-shell',
    imports: [NgComponentOutlet, NgTemplateOutlet, AppSvgIconComponent, MatTooltipModule],
    hostDirectives: [
        {
            directive: ShortcutListenerDirective,
            outputs: ['escape: escape', 'save: saveShortcut'],
        },
    ],
    host: {
        '(escape)': 'onEscape()',
        '(saveShortcut)': 'onShortcutSave()',
    },
    template: `
        @if (node() && panelComponent()) {
            <aside
                class="node-panel"
                [class.shake-attention]="isShaking()"
                [class.expanded]="isExpanded()"
            >
                <header class="dialog-header">
                    <div class="icon-and-title">
                        <i
                            [class]="node()!.icon"
                            [style.color]="node()!.color || '#685fff'"
                        ></i>
                        <span class="title">{{ nodeNameToDisplay() }}</span>
                    </div>
                    <div class="header-actions">
                        @if (panelInstanceSig()?.exportButtonTemplate?.()) {
                            <ng-container
                                [ngTemplateOutlet]="panelInstanceSig()!.exportButtonTemplate!()!"
                            ></ng-container>
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
                                <app-svg-icon icon="x"></app-svg-icon>
                            </button>
                        </div>
                    </div>
                </header>

                <main
                    [class.readonly]="!canEdit()"
                    [attr.inert]="canEdit() || selfGatesReadonly() ? null : ''"
                >
                    <ng-container
                        [ngComponentOutlet]="panelComponent()"
                        [ngComponentOutletInputs]="componentInputs()"
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
    public readonly canEdit = input<boolean>(true);
    public readonly save = output<NodeModel>();
    public readonly autosave = output<{ node: NodeModel; excludeFields: string[] }>();

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
        return n.node_name;
    });

    public readonly shouldShowExpandButton = computed(() => {
        const node = this.node();
        return (
            node &&
            node.type !== 'table' &&
            node.type !== NodeType.SCHEDULE_TRIGGER &&
            node.type !== 'classification-decision-table'
        );
    });

    protected readonly outlet = viewChild(NgComponentOutlet);
    protected readonly componentInputs = computed(() => {
        const node = this.node();

        return {
            node,
            isExpanded: this.isExpanded(),
            graphId: this.currentFlowId(),
            ...(node?.type === 'subgraph' ? { currentFlowId: this.currentFlowId() } : {}),
            // Only panels that declare a `canEdit` input should receive it — NgComponentOutlet
            // throws NG0303 for any component without a matching declared input.
            ...(node?.type === 'classification-decision-table' ? { canEdit: this.canEdit() } : {}),
        };
    });

    // Panels whose own template puts non-mutating navigation (e.g. tab switching)
    // alongside editable content — inert can't be selectively un-set on a
    // descendant, so these self-gate their content via their own `canEdit` input
    // instead of relying on the blanket <main> inert below.
    protected readonly selfGatesReadonly = computed(() => this.node()?.type === 'classification-decision-table');

    protected readonly isShaking = signal(false);
    protected readonly isExpanded = signal(false);
    private panelInstance:
        | (NodePanel & {
              onSaveSilently?: () => NodeModel | null;
              captureForValidation?: () => NodeModel | null;
              captureForBroadcast?: () => NodeModel | null;
              invalidPayloadFields?: () => string[];
          })
        | null = null;
    protected readonly panelInstanceSig = signal<{
        isDirty?: Signal<boolean>;
        isSaving?: Signal<boolean>;
        form?: { invalid: boolean };
        onSaveClick?: () => void;
        exportButtonTemplate?: () => TemplateRef<unknown> | undefined;
    } | null>(null);
    /** @deprecated the panel-header Save button was removed in EST-3020; no template usage remains. */
    protected readonly showSaveButton = computed(() => {
        const panel = this.panelInstanceSig();
        return (panel?.isDirty?.() ?? false) && !!panel?.onSaveClick;
    });
    private previousNodeId: string | null = null;
    private isUpdatingNode = false;
    private lastAutosaveSeq = 0;

    constructor(
        private sidePanelService: SidePanelService,
        private toastService: ToastService
    ) {
        effect(() => {
            // autosaveTrigger is a monotonic counter: react to each increment
            // (a field blur, toggle, etc.) exactly once and commit + broadcast
            // the panel state via performAutosave.
            const seq = this.sidePanelService.autosaveTrigger();
            if (seq === this.lastAutosaveSeq) return;
            this.lastAutosaveSeq = seq;
            if (this.panelInstance && !this.isUpdatingNode) {
                this.performAutosave();
            }
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
                    !this.isUpdatingNode
                ) {
                    this.isUpdatingNode = true;
                    this.performAutosave();
                }

                setTimeout(() => {
                    const outletRef = this.outlet();
                    if (outletRef?.componentInstance) {
                        this.panelInstance = outletRef.componentInstance as NodePanel & {
                            onSaveSilently?: () => NodeModel | null;
                            captureForBroadcast?: () => NodeModel | null;
                            invalidPayloadFields?: () => string[];
                        };
                        this.panelInstanceSig.set(
                            outletRef.componentInstance as {
                                isDirty?: Signal<boolean>;
                                isSaving?: Signal<boolean>;
                                form?: { invalid: boolean };
                                onSaveClick?: () => void;
                                exportButtonTemplate?: () => TemplateRef<unknown> | undefined;
                            }
                        );
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

    /** @deprecated the panel-header Save button was removed in EST-3020; no template usage remains. */
    protected onHeaderSaveClick(): void {
        this.panelInstanceSig()?.onSaveClick?.();
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
            this.toastService.error("Changes weren't saved — this node has invalid fields.");
        }
        this.sidePanelService.clearSelection();
    }

    private performAutosave(): void {
        const panel = this.panelInstance;
        if (!panel || typeof panel.onSave !== 'function') return;
        if (!(this.panelInstanceSig()?.isDirty?.() ?? true)) return;

        const updatedNode = panel.onSave();
        if (updatedNode) {
            this.autosave.emit({ node: updatedNode, excludeFields: [] });
            return;
        }

        if (typeof panel.captureForBroadcast !== 'function' || typeof panel.invalidPayloadFields !== 'function') {
            return;
        }
        const excludeFields = panel.invalidPayloadFields();
        if (excludeFields.length === 0) return;
        const partialNode = panel.captureForBroadcast();
        if (partialNode) {
            this.autosave.emit({ node: partialNode, excludeFields });
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

    /** @deprecated used only by the deprecated flow-graph emitSave(); no call sites. */
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
