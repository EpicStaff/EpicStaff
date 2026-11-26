import { CdkTrapFocus } from '@angular/cdk/a11y';
import { Dialog } from '@angular/cdk/dialog';
import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    HostListener,
    inject,
    Injector,
    OnInit,
    ResourceRef,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import { ActivatedRoute, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    AuthorshipDetailsDialogService,
    ButtonComponent,
    ConfirmationDialogService,
    UNSAVED_CHANGES_RESULT,
    UnsavedChangesDialogService,
} from '@shared/components';
import { HasPermissionDirective, HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml, takeQueryParams } from '@shared/utils';
import { defer, Observable, of, Subject } from 'rxjs';
import { defaultIfEmpty, finalize, map, switchMap, take, takeUntil, tap } from 'rxjs/operators';

import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
import { CREATE_AGENT_TOUR_ANCHORS } from '../../../create-agent-tour/create-agent-tour-anchors';
import { StorageItem } from '../../../files/models/storage.models';
import { StoragePreviewComponent } from '../../../files/pages/files-list-page/components/storage-page/components/storage-preview/storage-preview.component';
import { StorageContextActionEvent, StorageTreeFacade } from '../../../files/services/storage-tree-facade.service';
import { AgentDefinition, AgentInstruction, AgentSurfacePlace } from '../../models/agent-definition.model';
import { AgentFocus, ExplorerSectionId, GroupAssignTarget } from '../../models/explorer.model';
import { CreateSurfaceRequest } from '../../models/surface.model';
import { SURFACE_CATEGORIES, SurfaceCategoryConfig, SurfaceCategoryId } from '../../models/surface-category.model';
import {
    SurfaceUsage,
    surfaceUsageAgentCount,
    surfaceUsageFlowCount,
    surfaceUsageTotal,
} from '../../models/surface-usage.model';
import { BranchTreeNode } from '../../models/tree-node.model';
import { AgentSaveResult, AgentsPageStore } from '../../services/agents-page-store.service';
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
import { ExplorerMenuSubject } from './components/explorer/explorer-context-menu/explorer-menu.model';
import {
    AGENTS_SECTION_MENU_ACTION,
    canDuplicateAgent,
    GROUP_MENU_ACTION,
} from './components/explorer/explorer-menu.util';
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
        OverlayModule,
        CdkTrapFocus,
        MatTooltip,
        HasPermissionDirective,
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
    private readonly recycleBinSettings: RecycleBinSettingsService = inject(RecycleBinSettingsService);
    private readonly dialog: Dialog = inject(Dialog);
    private readonly injector: Injector = inject(Injector);
    private readonly route: ActivatedRoute = inject(ActivatedRoute);
    private readonly router: Router = inject(Router);
    private readonly permissions: PermissionsService = inject(PermissionsService);
    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);
    private readonly toast: ToastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
    protected readonly tourAnchors = CREATE_AGENT_TOUR_ANCHORS;

    /** Read-only mode when the active org can't mutate agents/surfaces. */
    protected readonly agentsReadOnly = computed<boolean>(() => {
        this.permissions.active();
        return !this.permissions.canAny(ResourceCode.Agents, [ActionCode.Create, ActionCode.Update, ActionCode.Delete]);
    });

    /** Storage preview is read-only when Files write actions are denied. */
    protected readonly filesReadOnly = computed<boolean>(() => {
        this.permissions.active();
        return !this.permissions.canAny(ResourceCode.Files, [ActionCode.Create, ActionCode.Update, ActionCode.Delete]);
    });

    /** Can the selected item (agent or surface) be duplicated in the active org? */
    protected readonly canDuplicateSelected = computed<boolean>(() => {
        this.permissions.active();
        const agent = this.store.selectedAgent();
        if (agent) return canDuplicateAgent(agent.id, this.store.surfaces(), this.permissions);
        if (this.store.selectedSurface()) return this.permissions.can(ResourceCode.Surfaces, ActionCode.Create);
        return false;
    });

    /** Can the selected item (agent or surface) be deleted in the active org? */
    protected readonly canDeleteSelected = computed<boolean>(() => {
        this.permissions.active();
        if (this.store.selectedAgent()) return this.permissions.can(ResourceCode.Agents, ActionCode.Delete);
        if (this.store.selectedSurface()) return this.permissions.can(ResourceCode.Surfaces, ActionCode.Delete);
        return false;
    });

    /**
     * Authorship is read-only, so anyone who can see the agent may view it — no permission gate.
     * Only agents: a selected surface renders the surface view, whose card menu has its own entry.
     */
    protected readonly canViewSelectedDetails = computed<boolean>(() => this.store.selectedAgent() !== null);

    /** Kebab is worth showing only if at least one action is permitted. */
    protected readonly canOpenHeaderMenu = computed<boolean>(
        () => this.canDuplicateSelected() || this.canViewSelectedDetails() || this.canDeleteSelected()
    );

    private readonly explorer = viewChild(ExplorerComponent);
    private readonly agentDetail = viewChild(AgentDetailComponent);
    private readonly headerMenuTrigger = viewChild<string, ElementRef<HTMLButtonElement>>('headerMenuTrigger', {
        read: ElementRef,
    });

    // Surfaces whose delete confirmation is being prepared or shown: a repeat click must not stack a second one.
    private readonly surfaceDeletesInFlight = new Set<number>();
    // `?agentId=` and `?surfaceId=`, taken from the URL at init and applied once the agent list has loaded
    private queryPreselect: Partial<Record<'agentId' | 'surfaceId', string>> = {};
    private sawLoading = false;

    /** Edits the agent editor holds that no save has been sent for. */
    private readonly editorDirty = signal<boolean>(false);
    /** The result of the agent save under way; null once it has landed. */
    private readonly agentSave = signal<Observable<AgentSaveResult> | null>(null);
    /** The agent save a leave waits on: the leave's dialog gives the reason it failed, so no toast does. */
    private saveAwaitedByLeave: Observable<AgentSaveResult> | null = null;
    /** Fires as a leave starts, so that one still waiting gives way to it. */
    private readonly leaveStarted = new Subject<void>();

    protected readonly hasUnsavedChanges = computed<boolean>(() => this.editorDirty() || this.agentSave() !== null);

    protected readonly selectedSurfaceUsageFailed = computed<boolean>(
        () => this.store.selectedSurfaceUsage.error() !== undefined
    );

    /** Null until the server has answered; the "Used by" button shows an ellipsis meanwhile. */
    protected readonly selectedSurfaceUsageCount = computed<number | null>(() => {
        const usage = this.store.selectedSurfaceUsage;
        return usage.hasValue() ? surfaceUsageTotal(usage.value()) : null;
    });

    protected readonly selectedSurfacePlace = computed<SurfaceCategoryConfig | null>(() => {
        const place = this.store.selectedSurfaceView()?.place;
        if (!place) return null;
        return SURFACE_CATEGORIES.find((c) => c.id === place) ?? null;
    });

    /** May the user move the selected agent or shared surface to another group? */
    private readonly canRegroupAgents = computed<boolean>(() => {
        this.permissions.active();
        return this.permissions.can(ResourceCode.Agents, ActionCode.Update);
    });

    private readonly canRegroupSurfaces = computed<boolean>(() => {
        this.permissions.active();
        return this.permissions.can(ResourceCode.Surfaces, ActionCode.Update);
    });

    protected readonly surfaceCrumbs = computed<DetailCrumb[]>(() => {
        const sv = this.store.selectedSurfaceView();
        if (!sv) return [];
        if (sv.ownerAgent) {
            // Under its agent the surface is never grouped itself: the crumb is the agent's group, and picking moves the agent.
            return [
                { label: 'AGENTS' },
                ...this.groupCrumb(sv.ownerAgent.group, this.canRegroupAgents()),
                { label: sv.ownerAgent.name, navAgentId: sv.ownerAgent.id },
                { label: 'Surfaces', navAgentSurfacesId: sv.ownerAgent.id },
                { label: sv.surface.name },
            ];
        }
        return [
            { label: 'SHARED SURFACES' },
            ...this.groupCrumb(sv.surface.group, sv.surface.owner_agent == null && this.canRegroupSurfaces()),
            { label: sv.surface.name },
        ];
    });

    /** Like an owned surface, an instruction shows its agent's group; picking one moves the agent. */
    protected readonly docCrumbs = computed<DetailCrumb[]>(() => {
        const doc = this.store.selectedAgentDoc();
        if (!doc) return [];
        return [
            { label: 'AGENTS' },
            ...this.groupCrumb(doc.agent.group, this.canRegroupAgents()),
            { label: doc.agent.name, navAgentId: doc.agent.id },
            { label: 'Instructions', navAgentInstructionsId: doc.agent.id },
            { label: doc.instruction.name },
        ];
    });

    protected readonly agentCrumbs = computed<DetailCrumb[]>(() => {
        const agent = this.store.selectedAgent();
        if (agent) {
            return [
                { label: 'AGENTS' },
                ...this.groupCrumb(agent.group, this.canRegroupAgents()),
                { label: agent.name },
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

        // An opened instruction can disappear (deleted, list shortened, agent gone): fall back to its agent.
        effect(() => {
            const selection = this.store.selectedNode();
            if (selection.kind !== 'agent-doc' || this.store.selectedAgentDoc()) return;
            if (this.store.agents().some((agent) => agent.id === selection.id)) this.store.selectAgent(selection.id);
            else this.store.clearSelection();
        });

        effect(() => {
            const loading = this.store.loading();
            if (loading) {
                this.sawLoading = true;
                return;
            }
            // Only the end of a load reruns this: not the lists and selection the preselect reads and sets.
            if (this.sawLoading) untracked(() => this.applyQueryPreselect());
        });
    }

    /** `?agentId=` selects that agent; `?surfaceId=` opens that surface where it lives. An unknown id is ignored. */
    private applyQueryPreselect(): void {
        const { agentId, surfaceId } = this.queryPreselect;
        this.queryPreselect = {};
        if (agentId != null) {
            const id = Number(agentId);
            if (this.store.agents().some((agent) => agent.id === id)) this.store.selectAgent(id);
        }
        if (surfaceId == null) return;
        const surface = this.store.surfaces().find((s) => s.id === Number(surfaceId));
        if (!surface) return;
        if (surface.owner_agent != null) {
            this.store.selectAgent(surface.owner_agent);
        } else {
            this.store.openSharedSurfaceSource(surface.id);
        }
    }

    ngOnInit(): void {
        this.queryPreselect = takeQueryParams(this.route, this.router, ['agentId', 'surfaceId']);
        this.store.load();
    }

    onDirtyChange(isDirty: boolean): void {
        this.editorDirty.set(isDirty);
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
                this.openDocInEdit = false;
                this.store.selectAgentDoc(node.agentId, node.instructionIndex);
            } else if (node.kind === 'group') {
                const surfacesMatch = /^agent:(\d+):surfaces$/.exec(node.id);
                const instructionsMatch = /^agent:(\d+):instructions$/.exec(node.id);
                if (surfacesMatch) {
                    this.storageFacade.selectedFile.set(null);
                    this.store.selectAgentSurfaces(Number(surfacesMatch[1]));
                } else if (instructionsMatch) {
                    this.storageFacade.selectedFile.set(null);
                    this.store.selectAgentInstructions(Number(instructionsMatch[1]));
                }
            }
        });
    }

    /** From a crumb or the instruction preview: like a click in the explorer, it waits for the agent's edits. */
    onOpenAgent(agentId: number, focus: AgentFocus = 'all'): void {
        this.guardUnsaved(() => this.store.selectAgent(agentId, focus));
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
        let saved: Observable<AgentSaveResult>;
        if (payload.id == null) {
            this.openDocInEdit = !!payload.openFirstInstructionInEdit;
            saved = this.store.saveNewAgent(
                {
                    name: payload.name,
                    description: payload.description,
                    instruction_list: payload.instruction_list,
                    llm_config: payload.llm_config,
                    fallback_llm_config: payload.fallback_llm_config,
                    fcm_llm_config: payload.fcm_llm_config,
                },
                !!payload.openFirstInstructionInEdit
            );
        } else {
            saved = this.store.updateAgent(payload.id, {
                name: payload.name,
                description: payload.description,
                llm_config: payload.llm_config,
                fallback_llm_config: payload.fallback_llm_config,
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
        this.editorDirty.set(false);
        this.agentSave.set(saved);
        saved.subscribe((result) => {
            if (this.agentSave() === saved) this.agentSave.set(null);
            if (!result.saved && saved !== this.saveAwaitedByLeave) this.toast.error(result.error);
        });
    }

    onSelectedInstructionList(instructionList: AgentInstruction[]): void {
        const agentId = this.store.selectedAgent()?.id;
        if (agentId == null) return;
        this.store.updateInstructionList(agentId, instructionList);
    }

    onCreateSurfaceForSelected(event: { body: CreateSurfaceRequest; place: SurfaceCategoryId }): void {
        const agentId = this.store.selectedAgent()?.id;
        if (agentId == null) return;
        this.store.createSurfaceForAgent(agentId, event.body, event.place);
    }

    onSetSharedForSelected(event: { surfaceIds: number[]; category: SurfaceCategoryId }): void {
        const agentId = this.store.selectedAgent()?.id;
        if (agentId == null) return;
        this.store.setSharedSurfacesInCategory(event.surfaceIds, agentId, event.category);
    }

    onDropSharedForSelected(event: { surfaceId: number; category: SurfaceCategoryId }): void {
        const agentId = this.store.selectedAgent()?.id;
        if (agentId == null) return;
        this.store.dropSharedSurfaceOnAgent(event.surfaceId, agentId, event.category);
    }

    onSetSurfacePlacesForSelected(event: { surfaceId: number; places: AgentSurfacePlace[] }): void {
        const agentId = this.store.selectedAgent()?.id;
        if (agentId == null) return;
        this.store.setSurfacePlaces(event.surfaceId, agentId, event.places);
    }

    onDetachSurfaceForSelected(surfaceId: number): void {
        const agentId = this.store.selectedAgent()?.id;
        if (agentId == null) return;
        this.store.detachSurfaceFromAgent(surfaceId, agentId);
    }

    onMakeAgentSpecificCopyForSelected(surfaceId: number): void {
        const agentId = this.store.selectedAgent()?.id;
        if (agentId == null) return;
        this.store.makeAgentSpecificCopy(surfaceId, agentId);
    }

    onCreateSurface(body: CreateSurfaceRequest): void {
        this.store.saveNewSurface(body);
        this.editorDirty.set(false);
    }

    onOpenUsage(): void {
        // Flow-editor changes made since the last load must show up.
        this.store.selectedSurfaceUsage.reload();
        this.openUsageDialog(this.store.selectedSurfaceUsage);
    }

    onOpenSurfaceUsage(surfaceId: number): void {
        this.openUsageDialog(this.store.openSurfaceUsage(surfaceId), () => this.store.closeSurfaceUsage());
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

    openDocInEdit = false;

    onOpenInstruction(request: { index: number; edit: boolean }): void {
        const id = this.store.selectedAgent()?.id;
        if (id == null) return;
        this.guardUnsaved(() => {
            this.openDocInEdit = request.edit;
            this.store.selectAgentDoc(id, request.index);
        });
    }

    onOpenSurfaceSource(surfaceId: number): void {
        this.guardUnsaved(() => this.store.openSharedSurfaceSource(surfaceId));
    }

    onDeleteAgent(agent: AgentDefinition): void {
        this.onDeleteAgentById(agent.id);
    }

    onDeleteAgentById(agentId: number): void {
        this.confirmDeleteAgent(agentId).subscribe((confirmed) => {
            if (!confirmed) return;
            this.store.deleteAgent(agentId);
            this.editorDirty.set(false);
        });
    }

    onDeleteSurface(surfaceId: number): void {
        this.confirmDeleteSurface(surfaceId).subscribe((confirmed) => {
            if (!confirmed) return;
            this.store.deleteSurface(surfaceId);
            this.editorDirty.set(false);
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

    readonly headerMenuOpen = signal(false);
    readonly headerMenuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    toggleHeaderMenu(event: MouseEvent): void {
        event.stopPropagation();
        this.headerMenuOpen.update((open) => !open);
    }

    closeHeaderMenu(): void {
        this.headerMenuOpen.set(false);
    }

    onHeaderDuplicate(): void {
        this.closeHeaderMenuToTrigger();
        const a = this.store.selectedAgent();
        if (a) {
            this.store.duplicateAgent(a.id);
            return;
        }
        const s = this.store.selectedSurface();
        if (s) this.store.duplicateSurface(s.id);
    }

    protected onHeaderViewDetails(): void {
        const agent = this.store.selectedAgent();
        this.closeHeaderMenu();
        if (agent) {
            this.authorshipDetailsDialog.open('Agent Details', agent, this.headerMenuTrigger()?.nativeElement);
        }
    }

    onHeaderDelete(): void {
        this.closeHeaderMenuToTrigger();
        this.onDeleteSelected();
    }

    /** Off the menu item first: a dialog the action opens returns the focus to what had it, and the item goes away. */
    private openUsageDialog(usage: ResourceRef<SurfaceUsage | undefined>, onClosed?: () => void): void {
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
                onClosed?.();
                if (typeof agentId !== 'number') return;
                this.guardUnsaved(() => {
                    this.storageFacade.selectedFile.set(null);
                    this.store.selectAgent(agentId);
                });
            });
    }

    private closeHeaderMenuToTrigger(): void {
        this.headerMenuTrigger()?.nativeElement.focus();
        this.closeHeaderMenu();
    }

    onExplorerTreeMenu(event: ExplorerTreeMenuEvent): void {
        // Read-only: it neither changes the selection nor discards edits, so no unsaved-changes prompt.
        if (event.action === 'view-details') {
            this.openExplorerAgentDetails(event);
            return;
        }
        if (event.action === 'export' && event.node.kind === 'agent') {
            this.store.exportAgent(event.node.agentId);
            return;
        }
        if (this.applyGroupMenuAction(event)) return;
        this.guardUnsaved(() => this.applyExplorerTreeMenu(event));
    }

    /**
     * Applies a group item of an explorer menu; false when the action is not one. Only "New agent in
     * <group>" changes the selection, so only it asks about unsaved changes.
     */
    private applyGroupMenuAction({ node, action }: ExplorerTreeMenuEvent): boolean {
        if (action.startsWith(GROUP_MENU_ACTION.moveToGroupPrefix)) {
            const target = this.groupAssignTarget(node);
            const value = action.slice(GROUP_MENU_ACTION.moveToGroupPrefix.length);
            if (target) this.store.moveToGroup(target, value === GROUP_MENU_ACTION.ungrouped ? null : Number(value));
            return true;
        }
        if (action === GROUP_MENU_ACTION.newGroup) {
            this.store.startNewGroup(this.groupAssignTarget(node));
            return true;
        }
        if (node.kind === 'section-header') {
            if (action !== GROUP_MENU_ACTION.collapseAll && action !== GROUP_MENU_ACTION.expandAll) return false;
            this.store.setAllGroupsCollapsed(node.section, action === GROUP_MENU_ACTION.collapseAll);
            return true;
        }
        if (node.kind !== 'group-header') return false;
        const groupId = node.groupId;
        switch (action) {
            case GROUP_MENU_ACTION.newAgentInGroup:
                this.guardUnsaved(() => {
                    this.storageFacade.selectedFile.set(null);
                    this.store.beginCreateAgent(groupId);
                });
                return true;
            case GROUP_MENU_ACTION.renameGroup:
                this.store.startRenameGroup(groupId);
                return true;
            case GROUP_MENU_ACTION.deleteGroup:
                this.confirmDeleteGroup(groupId);
                return true;
            default:
                return false;
        }
    }

    /** The agent or shared surface a menu was opened on; owned surfaces follow their agent and are never grouped. */
    private groupAssignTarget(node: ExplorerMenuSubject): GroupAssignTarget | null {
        if (node.kind === 'agent') return { kind: 'agent', id: node.agentId };
        if (node.kind === 'surface' && node.ownerAgentId == null) return { kind: 'surface', id: node.surfaceId };
        return null;
    }

    private confirmDeleteGroup(groupId: number): void {
        const group = this.store.groupsById().get(groupId);
        if (!group) return;
        const agentCount = this.store.agents().filter((agent) => agent.group === groupId).length;
        const surfaceCount = this.store.sharedSurfaces().filter((surface) => surface.group === groupId).length;
        const members = [
            agentCount > 0 ? `${agentCount} agent${agentCount === 1 ? '' : 's'}` : '',
            surfaceCount > 0 ? `${surfaceCount} shared surface${surfaceCount === 1 ? '' : 's'}` : '',
        ]
            .filter(Boolean)
            .join(' and ');
        const verb = agentCount + surfaceCount === 1 ? 'stays' : 'stay';
        const outcome = members ? `Its ${members} ${verb}, just without a group.` : 'The group is empty.';
        this.confirmationDialog
            .confirm(
                {
                    title: 'Ungroup',
                    message: `Remove the <strong>${escapeHtml(group.name)}</strong> group? ${outcome}`,
                    confirmText: 'Ungroup',
                    type: 'danger',
                    isShownBorder: true,
                },
                { width: DELETE_CONFIRM_DIALOG_WIDTH }
            )
            .subscribe((result) => {
                if (result === true) this.store.deleteGroup(groupId);
            });
    }

    /**
     * The group crumb: a picker when `editable`, else read-only text of the group. Nothing while
     * ungrouped; a group is assigned from the explorer (drag and drop, or Move to group).
     */
    private groupCrumb(groupId: number | null, editable: boolean): DetailCrumb[] {
        const group = groupId === null ? undefined : this.store.groupsById().get(groupId);
        if (!group) return [];
        return [{ label: group.name, group: { groupId: group.id, editable } }];
    }

    private applyExplorerTreeMenu({ node, action }: ExplorerTreeMenuEvent): void {
        if (node.kind === 'section-header') {
            if (action === AGENTS_SECTION_MENU_ACTION.import) this.store.importAgents();
            else if (action === AGENTS_SECTION_MENU_ACTION.export) this.store.startAgentExport();
            return;
        }

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
        return this.hasUnsavedChanges() ? this.leaveAgent() : true;
    }

    @HostListener('window:beforeunload', ['$event'])
    onBeforeUnload(event: BeforeUnloadEvent): void {
        if (!this.hasUnsavedChanges()) return;
        event.preventDefault();
        event.returnValue = '';
    }

    private confirmDeleteAgent(agentId: number): Observable<boolean> {
        if (!this.store.agents().some((a) => a.id === agentId)) return of(false);

        const ownedSurfaceCount = this.store.surfaces().filter((s) => s.owner_agent === agentId).length;
        const usage = { agents: 0, flows: 0, chats: 0 };
        const dialog = buildDeleteAgentDialog(usage, ownedSurfaceCount, this.recycleBinSettings.retentionDays());

        return this.confirmationDialog
            .confirm(dialog, { width: DELETE_CONFIRM_DIALOG_WIDTH })
            .pipe(map((result) => result === true));
    }

    private confirmDeleteSurface(surfaceId: number): Observable<boolean> {
        const surface = this.store.surfaces().find((s) => s.id === surfaceId);
        if (!surface) return of(false);

        if (this.surfaceDeletesInFlight.has(surfaceId)) return of(false);
        this.surfaceDeletesInFlight.add(surfaceId);

        const shared = surface.owner_agent == null;
        // Fetched fresh: the surface may not be the selected one, and a stale or missing count would understate the impact.
        return this.store.loadSurfaceUsage(surfaceId).pipe(
            switchMap((usageRaw) => {
                if (!usageRaw) return of(false);
                const usage = {
                    agents: shared ? surfaceUsageAgentCount(usageRaw) : 0,
                    flows: surfaceUsageFlowCount(usageRaw),
                    chats: 0,
                };
                const dialog = buildDeleteSurfaceDialog(
                    surface,
                    usage,
                    shared,
                    this.recycleBinSettings.retentionDays()
                );
                return this.confirmationDialog
                    .confirm(dialog, { width: DELETE_CONFIRM_DIALOG_WIDTH })
                    .pipe(map((result) => result === true));
            }),
            finalize(() => this.surfaceDeletesInFlight.delete(surfaceId))
        );
    }

    private guardUnsaved(action: () => void, onCancel?: () => void): void {
        if (!this.hasUnsavedChanges()) {
            action();
            return;
        }
        this.leaveAgent().subscribe((leave) => {
            if (leave) {
                action();
            } else {
                onCancel?.();
            }
        });
    }

    /**
     * True once the agent's edits are saved: the save under way, then what is left, sent as leaving the name field
     * sends it. No dialog for edits that can be saved — it takes the focus, and that blur would save them behind it.
     * A newer leave takes over from one still waiting, which then answers false.
     */
    private leaveAgent(): Observable<boolean> {
        this.leaveStarted.next();
        return this.saveAgentEdits().pipe(
            takeUntil(this.leaveStarted),
            defaultIfEmpty(false),
            tap((left) => {
                if (left) this.editorDirty.set(false);
            }),
            takeUntilDestroyed(this.destroyRef)
        );
    }

    private saveAgentEdits(): Observable<boolean> {
        const saveUnderWay = this.agentSave();
        if (saveUnderWay) {
            this.saveAwaitedByLeave = saveUnderWay;
            return saveUnderWay.pipe(
                // After the result, or when the leave stops waiting first: then a failure is toasted after all.
                finalize(() => {
                    if (this.saveAwaitedByLeave === saveUnderWay) this.saveAwaitedByLeave = null;
                }),
                switchMap((result) =>
                    result.saved ? this.saveEditsTypedMeanwhile() : this.confirmDiscardFailedEdits(result.error)
                )
            );
        }
        const detail = this.agentDetail();
        if (!detail || !this.editorDirty()) return of(true);
        if (!detail.canSave()) return this.confirmDiscardEdits();
        detail.savePendingEdits();
        return this.agentSave() ? this.saveAgentEdits() : of(true);
    }

    /** Sent only after a render: the editor must take in the saved agent first, or a created draft is created again. */
    private saveEditsTypedMeanwhile(): Observable<boolean> {
        if (!this.editorDirty()) return of(true);
        return new Observable<void>((subscriber) => {
            const render = afterNextRender(() => subscriber.next(), { injector: this.injector });
            return () => render.destroy();
        }).pipe(
            take(1),
            switchMap(() => this.saveAgentEdits())
        );
    }

    /** Edits that can't be saved as they are — no name, or one over the limit. Staying points the user at the name. */
    private confirmDiscardEdits(): Observable<boolean> {
        const drafting = this.store.isDraftingAgent();
        return this.askToDiscardEdits(
            drafting ? 'Agent not created' : 'Changes not saved',
            drafting
                ? "This agent hasn't been created yet. Fix the name to save it, or discard it."
                : "These changes can't be saved as they are. Fix the name to save them, or discard them."
        ).pipe(
            tap((leave) => {
                if (!leave) this.agentDetail()?.requireName();
            })
        );
    }

    /** Edits the server rejected. Discard & Leave is the way out when it keeps rejecting them. */
    private confirmDiscardFailedEdits(error: string): Observable<boolean> {
        return this.askToDiscardEdits("Couldn't save your changes", escapeHtml(error));
    }

    /**
     * True to drop the agent's edits and leave. There is no Save: there is nothing the server would take. Saves on blur
     * are held while the dialog is open — it takes the focus, and that blur must not save behind it.
     */
    private askToDiscardEdits(title: string, message: string): Observable<boolean> {
        return defer(() => {
            const detail = this.agentDetail();
            detail?.holdAutosave(true);
            return this.unsavedChangesDialog
                .confirm({
                    title,
                    message,
                    dontSaveText: 'Discard & Leave',
                    cancelText: 'Keep Editing',
                    type: 'warning',
                    showSave: false,
                })
                .pipe(
                    map((result) => result === UNSAVED_CHANGES_RESULT.dontSave),
                    tap((leave) => {
                        if (leave) detail?.discardEdits();
                    }),
                    finalize(() => detail?.holdAutosave(false))
                );
        });
    }

    private openExplorerAgentDetails({ node, trigger }: ExplorerTreeMenuEvent): void {
        if (node.kind !== 'agent') return;
        const agent = this.store.agents().find((candidate) => candidate.id === node.agentId);
        if (agent) this.authorshipDetailsDialog.open('Agent Details', agent, trigger);
    }
}
