import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    HostListener,
    inject,
    Injector,
    OnInit,
    signal,
    viewChild,
} from '@angular/core';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { Observable, of } from 'rxjs';
import { map } from 'rxjs/operators';

import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog';
import {
    UNSAVED_CHANGES_RESULT,
    UnsavedChangesDialogService,
} from '../../../../shared/components/unsaved-changes-dialog/unsaved-changes-dialog.service';
import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';
import { StorageItem } from '../../../files/models/storage.models';
import { StoragePreviewComponent } from '../../../files/pages/files-list-page/components/storage-page/components/storage-preview/storage-preview.component';
import { StorageContextActionEvent, StorageTreeFacade } from '../../../files/services/storage-tree-facade.service';
import { AgentDefinition } from '../../models/agent-definition.model';
import { ExplorerSectionId } from '../../models/explorer.model';
import { CreateSurfaceRequest } from '../../models/surface.model';
import { SURFACE_CATEGORIES, SurfaceCategoryConfig, SurfaceCategoryId } from '../../models/surface-category.model';
import { BranchTreeNode } from '../../models/tree-node.model';
import { AgentsPageStore } from '../../services/agents-page-store.service';
import { SurfaceCatalogsStore } from '../../services/surface-catalogs-store.service';
import {
    buildDeleteAgentDialog,
    buildDeleteSurfaceDialog,
    DELETE_CONFIRM_DIALOG_WIDTH,
} from '../../utils/delete-confirmation.util';
import { AgentDetailComponent, AgentSavePayload } from './components/agent-detail/agent-detail.component';
import { AgentDocPreviewComponent } from './components/agent-doc-preview/agent-doc-preview.component';
import { DetailCrumb, DetailHeaderComponent } from './components/detail-header/detail-header.component';
import { EmptyDetailComponent } from './components/empty-detail/empty-detail.component';
import { ExplorerComponent } from './components/explorer/explorer.component';
import {
    ExplorerTreeAttachSurfaceEvent,
    ExplorerTreeMenuEvent,
} from './components/explorer/tree-node/tree-node.component';
import { SurfaceDetailComponent } from './components/surface-detail/surface-detail.component';
import {
    SurfaceSummaryDialogComponent,
    SurfaceSummaryDialogData,
} from './components/surface-summary-dialog/surface-summary-dialog.component';
import {
    SurfaceUsage,
    SurfaceUsageDialogComponent,
    SurfaceUsageDialogData,
} from './components/surface-usage-dialog/surface-usage-dialog.component';

@Component({
    selector: 'app-agent-definitions-page',
    imports: [
        HideInlineSubtitleOnOverflowDirective,
        ButtonComponent,
        ExplorerComponent,
        AgentDetailComponent,
        SurfaceDetailComponent,
        EmptyDetailComponent,
        StoragePreviewComponent,
        AgentDocPreviewComponent,
        DetailHeaderComponent,
        AppSvgIconComponent,
    ],
    templateUrl: './agent-definitions-page.component.html',
    styleUrls: ['./agent-definitions-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [AgentsPageStore, StorageTreeFacade, SurfaceCatalogsStore],
})
export class AgentDefinitionsPageComponent implements OnInit, CanComponentDeactivate {
    protected readonly store: AgentsPageStore = inject(AgentsPageStore);
    protected readonly storageFacade: StorageTreeFacade = inject(StorageTreeFacade);
    private readonly unsavedChangesDialog: UnsavedChangesDialogService = inject(UnsavedChangesDialogService);
    private readonly confirmationDialog: ConfirmationDialogService = inject(ConfirmationDialogService);
    private readonly dialog: Dialog = inject(Dialog);
    private readonly injector: Injector = inject(Injector);

    private readonly explorer = viewChild(ExplorerComponent);

    protected readonly hasUnsavedChanges = signal<boolean>(false);

    protected readonly selectedSurfaceUsage = computed<SurfaceUsage | null>(() => {
        const sv = this.store.selectedSurfaceView();
        return sv ? this.store.surfaceUsage(sv.surface.id) : null;
    });

    protected readonly selectedSurfaceUsageCount = computed<number>(() => {
        const u = this.selectedSurfaceUsage();
        return u ? u.agents.length + u.flows.length + u.chats.length : 0;
    });

    protected readonly selectedSurfacePlace = computed<SurfaceCategoryConfig | null>(() => {
        const place = this.store.selectedSurfaceView()?.place;
        if (!place) return null;
        return SURFACE_CATEGORIES.find((c) => c.id === place) ?? null;
    });

    protected readonly surfaceCrumbs = computed<DetailCrumb[]>(() => {
        const sv = this.store.selectedSurfaceView();
        if (!sv) return [];
        if (sv.ownerAgent) {
            return [
                { label: 'AGENTS' },
                { label: sv.ownerAgent.name, navAgentId: sv.ownerAgent.id },
                { label: 'Surfaces', navAgentSurfacesId: sv.ownerAgent.id },
                { label: sv.surface.name },
            ];
        }
        return [{ label: 'SHARED SURFACES' }, { label: sv.surface.name }];
    });

    protected readonly agentCrumbs = computed<DetailCrumb[]>(() => {
        const agent = this.store.selectedAgent();
        if (agent) return [{ label: 'AGENTS' }, { label: agent.name }];
        const surfacesAgent = this.store.surfacesOnlyAgent();
        if (surfacesAgent) {
            return [
                { label: 'AGENTS' },
                { label: surfacesAgent.name, navAgentId: surfacesAgent.id },
                { label: 'Surfaces' },
            ];
        }
        const s = this.store.selectedSurface();
        if (s) return [{ label: 'SHARED SURFACES' }, { label: s.name }];
        return [];
    });

    constructor() {
        this.storageFacade.init({ watchRefreshTick: false });

        effect(() => {
            const file = this.storageFacade.selectedFile();
            if (!file && this.store.selectedNode().kind === 'storage') {
                this.store.clearSelection();
            }
        });
    }

    ngOnInit(): void {
        this.store.load();
    }

    onDirtyChange(isDirty: boolean): void {
        this.hasUnsavedChanges.set(isDirty);
    }

    onSelectNode(node: BranchTreeNode): void {
        this.guardUnsaved(() => {
            if (node.kind === 'surface') {
                this.storageFacade.selectedFile.set(null);
                this.store.selectSurface(node.surfaceId, node.ownerAgentId);
            } else if (node.kind === 'agent') {
                this.storageFacade.selectedFile.set(null);
                this.store.selectAgent(node.agentId);
            } else if (node.kind === 'agent-doc') {
                this.storageFacade.selectedFile.set(null);
                this.store.selectAgentDoc(node.agentId, node.docType);
            } else if (node.kind === 'group') {
                const match = /^agent:(\d+):surfaces$/.exec(node.id);
                if (match) {
                    this.storageFacade.selectedFile.set(null);
                    this.store.selectAgentSurfaces(Number(match[1]));
                }
            }
        });
    }

    onSelectStorageItem(item: StorageItem): void {
        const previous = this.storageFacade.selectedFile();
        this.guardUnsaved(
            () => {
                this.storageFacade.selectedFile.set(item);
                this.store.selectStorage(item.path);
            },
            () => {
                if (previous) this.explorer()?.storageSection()?.restoreSelection(previous);
            }
        );
    }

    onAddInSection(section: ExplorerSectionId): void {
        this.guardUnsaved(() => {
            if (section === 'surfaces') this.store.beginCreateSurface();
            else if (section === 'agents') this.store.beginCreateAgent();
        });
    }

    onExplorerAttachSharedSurface(event: ExplorerTreeAttachSurfaceEvent): void {
        this.store.dropSharedSurfaceOnAgent(event.surfaceId, event.agentId);
    }

    onAddAgent(): void {
        this.guardUnsaved(() => this.store.beginCreateAgent());
    }

    onPreviewContextAction(event: StorageContextActionEvent): void {
        if (event.action === 'rename') {
            if (!this.store.showSidebar()) {
                this.store.showSidebar.set(true);
                setTimeout(() => this.explorer()?.storageSection()?.startRename(event.item));
            } else {
                this.explorer()?.storageSection()?.startRename(event.item);
            }
        } else {
            this.storageFacade.onContextAction(event);
        }
    }

    onPreviewBreadcrumb(path: string): void {
        this.store.showSidebar.set(true);
        this.storageFacade.expandAndSelectPath(path);
    }

    onSaveAgent(payload: AgentSavePayload): void {
        if (payload.id == null) {
            this.store.saveNewAgent({
                name: payload.name,
                description: payload.description,
                instructions: payload.instructions,
                llm_config: payload.llm_config,
                fcm_llm_config: payload.fcm_llm_config,
            });
        } else {
            this.store.updateAgent(payload.id, {
                name: payload.name,
                description: payload.description,
                instructions: payload.instructions,
                llm_config: payload.llm_config,
                fcm_llm_config: payload.fcm_llm_config,
                max_iter: payload.max_iter,
                max_rpm: payload.max_rpm,
                max_execution_time: payload.max_execution_time,
                cache: payload.cache,
                max_retry_limit: payload.max_retry_limit,
                default_temperature: payload.default_temperature,
                max_tool_calls: payload.max_tool_calls,
                tool_timeout: payload.tool_timeout,
                max_consecutive_failures: payload.max_consecutive_failures,
                schema_max_retries: payload.schema_max_retries,
            });
        }
        this.hasUnsavedChanges.set(false);
    }

    onCreateSurface(body: CreateSurfaceRequest): void {
        this.store.saveNewSurface(body);
        this.hasUnsavedChanges.set(false);
    }

    onOpenUsage(): void {
        const usage = this.selectedSurfaceUsage();
        if (!usage) return;
        this.dialog
            .open<number | undefined, SurfaceUsageDialogData>(SurfaceUsageDialogComponent, {
                width: 'calc(100vw - 2rem)',
                height: 'calc(100vh - 2rem)',
                maxWidth: '100vw',
                panelClass: 'surface-usage-dialog-panel',
                injector: this.injector,
                data: { usage },
            })
            .closed.subscribe((agentId) => {
                if (typeof agentId !== 'number') return;
                this.guardUnsaved(() => {
                    this.storageFacade.selectedFile.set(null);
                    this.store.selectAgent(agentId);
                });
            });
    }

    onViewSummary(event: { place: SurfaceCategoryId; surfaceIds: number[] }): void {
        this.store.combineSurfaces(event.surfaceIds).subscribe((combined) => {
            if (!combined) return;
            const label = SURFACE_CATEGORIES.find((c) => c.id === event.place)?.label ?? event.place;
            this.dialog.open<void, SurfaceSummaryDialogData>(SurfaceSummaryDialogComponent, {
                width: 'calc(100vw - 2rem)',
                height: 'calc(100vh - 2rem)',
                maxWidth: '100vw',
                panelClass: 'surface-summary-dialog-panel',
                injector: this.injector,
                data: { combined, placeLabel: label, hideInstructions: true, hideDescriptions: true },
            });
        });
    }

    onDeleteAgent(agent: AgentDefinition): void {
        this.onDeleteAgentById(agent.id);
    }

    onDeleteAgentById(agentId: number): void {
        this.confirmDeleteAgent(agentId).subscribe((confirmed) => {
            if (!confirmed) return;
            this.store.deleteAgent(agentId);
            this.hasUnsavedChanges.set(false);
        });
    }

    onDeleteSurface(surfaceId: number): void {
        this.confirmDeleteSurface(surfaceId).subscribe((confirmed) => {
            if (!confirmed) return;
            this.store.deleteSurface(surfaceId);
            this.hasUnsavedChanges.set(false);
        });
    }

    onDeleteSelected(): void {
        const a = this.store.selectedAgent();
        if (a) {
            this.onDeleteAgent(a);
            return;
        }
        const s = this.store.selectedSurface();
        if (s) this.onDeleteSurface(s.id);
    }

    onExplorerTreeMenu(event: ExplorerTreeMenuEvent): void {
        this.guardUnsaved(() => this.applyExplorerTreeMenu(event));
    }

    private applyExplorerTreeMenu({ node, action }: ExplorerTreeMenuEvent): void {
        if (node.kind === 'agent') {
            if (action === 'delete') this.onDeleteAgentById(node.agentId);
            else if (action === 'duplicate') this.store.duplicateAgent(node.agentId);
            return;
        }
        if (node.kind !== 'surface') return;

        switch (action) {
            case 'delete':
                this.onDeleteSurface(node.surfaceId);
                break;
            case 'duplicate':
                this.store.duplicateSurface(node.surfaceId);
                break;
            case 'open-source':
                this.store.openSharedSurfaceSource(node.surfaceId);
                break;
            case 'detach':
                if (node.ownerAgentId != null) {
                    this.store.detachSurfaceFromAgent(node.surfaceId, node.ownerAgentId);
                }
                break;
        }
    }

    canDeactivate(): boolean | Observable<boolean> {
        if (!this.hasUnsavedChanges()) return true;
        return this.unsavedChangesDialog.confirmUnsavedChanges().pipe(
            map((result) => {
                if (result === UNSAVED_CHANGES_RESULT.dontSave) {
                    this.hasUnsavedChanges.set(false);
                    return true;
                }
                return false;
            })
        );
    }

    @HostListener('window:beforeunload', ['$event'])
    onBeforeUnload(event: BeforeUnloadEvent): void {
        if (!this.hasUnsavedChanges()) return;
        event.preventDefault();
        event.returnValue = '';
    }

    private confirmDeleteAgent(agentId: number): Observable<boolean> {
        const agent = this.store.agents().find((a) => a.id === agentId);
        if (!agent) return of(false);

        const ownedSurfaceCount = this.store.surfaces().filter((s) => s.owner_agent === agentId).length;
        const usage = { agents: 0, flows: 0, chats: 0 };
        const dialog = buildDeleteAgentDialog(agent, usage, ownedSurfaceCount);

        return this.confirmationDialog
            .confirm(dialog, { width: DELETE_CONFIRM_DIALOG_WIDTH })
            .pipe(map((result) => result === true));
    }

    private confirmDeleteSurface(surfaceId: number): Observable<boolean> {
        const surface = this.store.surfaces().find((s) => s.id === surfaceId);
        if (!surface) return of(false);

        const usageRaw = this.store.surfaceUsage(surfaceId);
        const shared = surface.owner_agent == null;
        const usage = {
            agents: shared ? usageRaw.agents.length : 0,
            flows: usageRaw.flows.length,
            chats: usageRaw.chats.length,
        };
        const dialog = buildDeleteSurfaceDialog(surface, usage, shared);

        return this.confirmationDialog
            .confirm(dialog, { width: DELETE_CONFIRM_DIALOG_WIDTH })
            .pipe(map((result) => result === true));
    }

    private guardUnsaved(action: () => void, onCancel?: () => void): void {
        if (!this.hasUnsavedChanges()) {
            action();
            return;
        }
        this.unsavedChangesDialog.confirmUnsavedChanges().subscribe((result) => {
            if (result === UNSAVED_CHANGES_RESULT.dontSave) {
                this.hasUnsavedChanges.set(false);
                action();
            } else {
                onCancel?.();
            }
        });
    }
}
