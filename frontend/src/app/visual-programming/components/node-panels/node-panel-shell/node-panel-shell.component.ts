import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal, viewChild } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ShortcutListenerDirective } from '../../../core/directives/shortcut-listener.directive';
import { PANEL_COMPONENT_MAP } from '../../../core/enums/node-panel.map';
import { NodeModel } from '../../../core/models/node.model';
import { NodePanel } from '../../../core/models/node-panel.interface';
import { SidePanelService } from '../../../services/side-panel.service';

@Component({
    standalone: true,
    selector: 'app-node-panel-shell',
    imports: [NgComponentOutlet, AppSvgIconComponent],
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
            <aside class="node-panel" [class.shake-attention]="isShaking()" [class.expanded]="isExpanded()">
                <header class="dialog-header">
                    <div class="icon-and-title">
                        <i [class]="node()!.icon" [style.color]="node()!.color || '#685fff'"></i>
                        <span class="title">{{ nodeNameToDisplay() }}</span>
                    </div>
                    <div class="header-actions">
                        @if (shouldShowExpandButton()) {
                            <button class="expand-btn" aria-label="Toggle panel size" (click)="toggleExpanded()">
                                <app-svg-icon
                                    [icon]="isExpanded() ? 'arrows-minimize' : 'arrows-maximize'"
                                    size="1.25rem"
                                ></app-svg-icon>
                            </button>
                        }
                        <div class="close-action">
                            <span class="esc-label">ESC</span>
                            <button class="close-btn" aria-label="Close dialog" (click)="onCloseClick()">
                                <app-svg-icon icon="x"></app-svg-icon>
                            </button>
                        </div>
                    </div>
                </header>

                <main>
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
        return n.node_name;
    });

    public readonly shouldShowExpandButton = computed(() => {
        const node = this.node();
        return node && node.type !== 'table' && node.type !== 'classification-decision-table';
    });

    protected readonly outlet = viewChild(NgComponentOutlet);
    protected readonly componentInputs = computed(() => {
        const node = this.node();

        return {
            node,
            isExpanded: this.isExpanded(),
            ...(node?.type === 'subgraph' ? { currentFlowId: this.currentFlowId() } : {}),
        };
    });

    protected readonly isShaking = signal(false);
    protected readonly isExpanded = signal(false);
    private panelInstance: (NodePanel & { onSaveSilently?: () => NodeModel | null }) | null = null;
    private previousNodeId: string | null = null;
    private isUpdatingNode = false;
    private isAutosaving = false;

    constructor(private sidePanelService: SidePanelService) {
        effect(() => {
            const trigger = this.sidePanelService.autosaveTrigger();
            if (trigger && this.panelInstance && !this.isAutosaving) {
                this.isAutosaving = true;
                this.performAutosave();
                setTimeout(() => {
                    this.sidePanelService.clearAutosaveTrigger();
                    this.isAutosaving = false;
                }, 100);
            }
        });

        effect(() => {
            const node = this.node();
            if (node) {
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
                        this.previousNodeId = node.id;
                        this.isUpdatingNode = false;
                    }
                }, 0);
            } else {
                // Reset when no node is selected
                this.panelInstance = null;
                this.previousNodeId = null;
                this.isUpdatingNode = false;
                this.isAutosaving = false;
            }
        });
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
        this.isExpanded.set(true);
    }

    private saveSidePanel(): void {
        if (this.panelInstance && typeof this.panelInstance.onSave === 'function') {
            const updatedNode = this.panelInstance.onSave();
            if (updatedNode) {
                this.save.emit(updatedNode);
            }
        }
    }

    private performAutosave(): void {
        if (this.panelInstance && typeof this.panelInstance.onSave === 'function') {
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
}
