import { computed, inject, Injectable, signal } from '@angular/core';
import { computeUniqueCopyName } from '@shared/utils';
import { forkJoin, Observable, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications/toast.service';
import {
    AgentDefaultSurface,
    AgentDefinition,
    AgentMetadata,
    AgentSurfacePlace,
    CreateAgentDefinitionRequest,
    PartialUpdateAgentDefinitionRequest,
} from '../models/agent-definition.model';
import { EXPLORER_SECTIONS, ExplorerSectionId, ExplorerSelection, NO_SELECTION } from '../models/explorer.model';
import { CombinedSurface, CreateSurfaceRequest, PartialUpdateSurfaceRequest, Surface } from '../models/surface.model';
import {
    categoryToPlace,
    placeToCategory,
    SURFACE_CATEGORIES,
    SurfaceCategoryId,
} from '../models/surface-category.model';
import { AgentDocType, BranchTreeNode } from '../models/tree-node.model';
import { AgentDefinitionsApiService } from './agent-definitions-api.service';
import { SurfacesApiService } from './surfaces-api.service';

export type SelectedNode = ExplorerSelection;

export interface SurfaceView {
    surface: Surface;
    ownerAgent: AgentDefinition | null;
    readOnly: boolean;
    place: SurfaceCategoryId | null;
}

const VISIBLE_SECTIONS_STORAGE_KEY = 'agents-explorer/visibleSections';

function loadVisibleSections(): Set<ExplorerSectionId> {
    const all = EXPLORER_SECTIONS.map((s) => s.id);
    try {
        const raw = localStorage.getItem(VISIBLE_SECTIONS_STORAGE_KEY);
        if (!raw) return new Set(all);
        const parsed = JSON.parse(raw) as ExplorerSectionId[];
        const valid = parsed.filter((id) => all.includes(id));
        const set = new Set(valid);
        set.add('agents');
        return set;
    } catch {
        return new Set(all);
    }
}

@Injectable()
export class AgentsPageStore {
    private readonly agentsApi: AgentDefinitionsApiService = inject(AgentDefinitionsApiService);
    private readonly surfacesApi: SurfacesApiService = inject(SurfacesApiService);
    private readonly toast: ToastService = inject(ToastService);

    readonly agents = signal<AgentDefinition[]>([]);
    readonly surfaces = signal<Surface[]>([]);
    readonly loading = signal<boolean>(false);
    readonly saving = signal<boolean>(false);
    readonly agentSaveErrorTick = signal<number>(0);
    readonly search = signal<string>('');
    readonly selectedNode = signal<ExplorerSelection>(NO_SELECTION);
    readonly showSidebar = signal<boolean>(true);

    readonly expandedSections = signal<Set<ExplorerSectionId>>(new Set(['agents']));

    readonly visibleSections = signal<Set<ExplorerSectionId>>(loadVisibleSections());

    readonly storageActivated = signal<boolean>(false);

    readonly visibleSectionsCount = computed<number>(() => this.visibleSections().size);

    isSectionVisible(id: ExplorerSectionId): boolean {
        return this.visibleSections().has(id);
    }

    isSectionExpanded(id: ExplorerSectionId): boolean {
        return this.expandedSections().has(id);
    }

    toggleSection(id: ExplorerSectionId): void {
        this.expandedSections.update((set) => {
            const next = new Set(set);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
        if (id === 'storage' && this.expandedSections().has('storage')) {
            this.storageActivated.set(true);
        }
    }

    setVisibleSections(ids: Set<ExplorerSectionId>): void {
        const next = new Set(ids);
        next.add('agents');
        this.visibleSections.set(next);
        this.persistVisibleSections();
    }

    private persistVisibleSections(): void {
        try {
            localStorage.setItem(VISIBLE_SECTIONS_STORAGE_KEY, JSON.stringify([...this.visibleSections()]));
        } catch {}
    }

    readonly selectedAgent = computed<AgentDefinition | null>(() => {
        const s = this.selectedNode();
        if (s.kind !== 'agent') return null;
        return this.agents().find((a) => a.id === s.id) ?? null;
    });

    readonly selectedSurface = computed<Surface | null>(() => {
        const s = this.selectedNode();
        if (s.kind !== 'surface') return null;
        return this.surfaces().find((sf) => sf.id === s.id) ?? null;
    });

    readonly selectedSurfaceView = computed<SurfaceView | null>(() => {
        const s = this.selectedNode();
        if (s.kind !== 'surface') return null;
        const surface = this.surfaces().find((sf) => sf.id === s.id);
        if (!surface) return null;
        const ownerAgent = s.ownerAgentId != null ? (this.agents().find((a) => a.id === s.ownerAgentId) ?? null) : null;
        const isShared = this.isSurfaceShared(surface.id);
        const readOnly = isShared && ownerAgent != null;
        const assignment = ownerAgent?.default_surfaces.find((ds) => ds.surface === surface.id);
        const place = assignment ? placeToCategory(assignment.place) : null;
        return { surface, ownerAgent, readOnly, place };
    });

    readonly surfacesOnlyAgent = computed<AgentDefinition | null>(() => {
        const s = this.selectedNode();
        if (s.kind !== 'agent-surfaces') return null;
        return this.agents().find((a) => a.id === s.id) ?? null;
    });

    readonly isDraftingAgent = computed<boolean>(() => this.selectedNode().kind === 'draft-agent');

    readonly isDraftingSurface = computed<boolean>(() => this.selectedNode().kind === 'draft-surface');

    readonly isStorageSelected = computed<boolean>(() => this.selectedNode().kind === 'storage');

    readonly selectedAgentDoc = computed<{ agent: AgentDefinition; docType: AgentDocType } | null>(() => {
        const s = this.selectedNode();
        if (s.kind !== 'agent-doc') return null;
        const agent = this.agents().find((a) => a.id === s.id);
        return agent ? { agent, docType: s.docType } : null;
    });

    readonly sharedSurfaceIdSet = computed<ReadonlySet<number>>(
        () =>
            new Set(
                this.surfaces()
                    .filter((s) => s.owner_agent == null)
                    .map((s) => s.id)
            )
    );

    isSurfaceShared(id: number): boolean {
        return this.sharedSurfaceIdSet().has(id);
    }

    isBootDoc(agentId: number): boolean {
        const agent = this.agents().find((a) => a.id === agentId);
        return agent?.metadata?.instructions_format === 'markdown';
    }

    setBootDoc(agentId: number, isDoc: boolean): void {
        const agent = this.agents().find((a) => a.id === agentId);
        if (!agent) return;
        if (this.isBootDoc(agentId) === isDoc) return;
        const metadata: AgentMetadata = {
            ...agent.metadata,
            instructions_format: isDoc ? 'markdown' : 'text',
        };
        this.updateAgent(agentId, { metadata });
    }

    /**
     * Overwrite an agent's boot instructions with extracted file text, switch
     * the field to markdown-doc mode, and open the doc view — all in a single
     * patch so the user lands on the Boot_Instructions.md doc showing the text.
     */
    applyBootDocFromText(agentId: number, text: string): void {
        const agent = this.agents().find((a) => a.id === agentId);
        if (!agent) return;
        const metadata: AgentMetadata = { ...agent.metadata, instructions_format: 'markdown' };
        this.saving.set(true);
        this.agentsApi.partialUpdate(agentId, { instructions: text, metadata }).subscribe({
            next: (updated) => {
                this.agents.update((list) => list.map((a) => (a.id === agentId ? updated : a)));
                this.saving.set(false);
                this.selectAgentDoc(agentId, 'boot');
            },
            error: (err) => {
                this.saving.set(false);
                this.agentSaveErrorTick.update((n) => n + 1);
                this.toast.error(this.extractError(err, 'Failed to update boot instructions'));
            },
        });
    }

    selectAgent(id: number): void {
        this.selectedNode.set({ kind: 'agent', id });
    }

    selectSurface(id: number, ownerAgentId?: number): void {
        this.selectedNode.set({ kind: 'surface', id, ownerAgentId });
    }

    selectAgentSurfaces(id: number): void {
        this.selectedNode.set({ kind: 'agent-surfaces', id });
    }

    selectAgentDoc(id: number, docType: AgentDocType): void {
        this.selectedNode.set({ kind: 'agent-doc', id, docType });
    }

    openSharedSurfaceSource(id: number): void {
        this.visibleSections.update((set) => {
            if (set.has('surfaces')) return set;
            const next = new Set(set);
            next.add('surfaces');
            return next;
        });
        this.persistVisibleSections();
        this.expandedSections.update((set) => {
            if (set.has('surfaces')) return set;
            const next = new Set(set);
            next.add('surfaces');
            return next;
        });
        this.selectSurface(id);
    }

    selectStorage(path: string): void {
        this.selectedNode.set({ kind: 'storage', path });
    }

    clearSelection(): void {
        this.selectedNode.set(NO_SELECTION);
    }

    setSearch(q: string): void {
        this.search.set(q);
    }

    toggleSidebar(): void {
        this.showSidebar.update((v) => !v);
    }

    surfaceUsage(surfaceId: number): {
        agents: { agentId: number; agentName: string; place: SurfaceCategoryId; placeLabel: string }[];
        flows: never[];
        chats: never[];
    } {
        const agents = this.agents().flatMap((a) =>
            a.default_surfaces
                .filter((ds) => ds.surface === surfaceId)
                .map((ds) => {
                    const category = placeToCategory(ds.place);
                    return {
                        agentId: a.id,
                        agentName: a.name,
                        place: category,
                        placeLabel: SURFACE_CATEGORIES.find((c) => c.id === category)?.label ?? category,
                    };
                })
        );
        return { agents, flows: [], chats: [] };
    }

    readonly sharedSurfaces = computed<Surface[]>(() => this.surfaces().filter((s) => s.owner_agent == null));

    readonly surfacesByAgent = computed<Map<number, Surface[]>>(() => {
        const byId = new Map(this.surfaces().map((s) => [s.id, s]));
        const map = new Map<number, Surface[]>();
        for (const a of this.agents()) {
            const seen = new Set<number>();
            const list: Surface[] = [];
            for (const ds of a.default_surfaces) {
                if (seen.has(ds.surface)) continue;
                const surface = byId.get(ds.surface);
                if (!surface) continue;
                seen.add(ds.surface);
                list.push(surface);
            }
            if (list.length) map.set(a.id, list);
        }
        return map;
    });

    readonly agentsTree = computed<BranchTreeNode[]>(() => {
        const q = this.search().trim().toLowerCase();
        const matchLabel = (label: string) => !q || label.toLowerCase().includes(q);
        const byAgent = this.surfacesByAgent();

        return this.agents()
            .map((a) => {
                const agentMatches = matchLabel(a.name);
                const ownSurfaces: BranchTreeNode[] = (byAgent.get(a.id) ?? [])
                    .filter((s) => agentMatches || matchLabel(s.name))
                    .map((s) => ({
                        kind: 'surface',
                        surfaceId: s.id,
                        label: s.name,
                        locked: !this.isSurfaceShared(s.id),
                        shared: this.isSurfaceShared(s.id),
                        ownerAgentId: a.id,
                    }));

                const children: BranchTreeNode[] = [];
                if (a.metadata?.instructions_format === 'markdown') {
                    children.push({
                        kind: 'agent-doc',
                        agentId: a.id,
                        docType: 'boot',
                        label: 'Boot_Instructions.md',
                        placeholder: true,
                    });
                }
                children.push({
                    kind: 'group',
                    id: `agent:${a.id}:surfaces`,
                    label: 'Surfaces',
                    icon: 'surfaces-tab',
                    children: ownSurfaces,
                    defaultExpanded: false,
                });

                return {
                    node: {
                        kind: 'agent',
                        agentId: a.id,
                        label: a.name,
                        children,
                    } as BranchTreeNode,
                    agentMatches,
                    matchingSurfaces: ownSurfaces.length,
                };
            })
            .filter((entry) => !q || entry.agentMatches || entry.matchingSurfaces > 0)
            .map((entry) => entry.node);
    });

    readonly surfacesTree = computed<BranchTreeNode[]>(() => {
        const q = this.search().trim().toLowerCase();
        const matchLabel = (label: string) => !q || label.toLowerCase().includes(q);

        return this.sharedSurfaces()
            .filter((s) => matchLabel(s.name))
            .map((s) => ({ kind: 'surface', surfaceId: s.id, label: s.name, locked: false }) as BranchTreeNode);
    });

    load(): void {
        this.loading.set(true);
        forkJoin({
            agents: this.agentsApi.getAgentDefinitions(),
            surfaces: this.surfacesApi.getSurfaces(),
        }).subscribe({
            next: ({ agents, surfaces }) => {
                const agentsOk = Array.isArray(agents);
                const surfacesOk = Array.isArray(surfaces);
                this.agents.set(agentsOk ? agents : []);
                this.surfaces.set(surfacesOk ? surfaces : []);
                this.loading.set(false);
                if (!agentsOk || !surfacesOk) {
                    this.toast.error('Failed to load agents and surfaces');
                }
            },
            error: (err) => {
                this.agents.set([]);
                this.surfaces.set([]);
                this.loading.set(false);
                this.toast.error(this.extractError(err, 'Failed to load agents and surfaces'));
            },
        });
    }

    combineSurfaces(surfaceIds: number[]): Observable<CombinedSurface | null> {
        return this.surfacesApi.combine(surfaceIds).pipe(
            catchError((err) => {
                this.toast.error(this.extractError(err, 'Failed to combine surfaces'));
                return of(null);
            })
        );
    }

    beginCreateSurface(): void {
        this.selectedNode.set({ kind: 'draft-surface', id: null });
    }

    beginCreateAgent(): void {
        this.selectedNode.set({ kind: 'draft-agent', id: null });
    }

    cancelDraft(): void {
        const s = this.selectedNode();
        if (s.kind === 'draft-agent' || s.kind === 'draft-surface') {
            this.clearSelection();
        }
    }

    makeSurfaceShared(id: number): void {
        this.updateSurface(id, { owner_agent: null });
    }

    attachSharedSurfaceToAgent(surfaceId: number, agentId: number): void {
        this.assignSurfaceToAgent(surfaceId, agentId, 'all');
    }

    dropSharedSurfaceOnAgent(surfaceId: number, agentId: number, category?: SurfaceCategoryId): void {
        const agent = this.agents().find((a) => a.id === agentId);
        if (!agent) return;
        if (agent.default_surfaces.some((ds) => ds.surface === surfaceId)) {
            const name = this.surfaces().find((s) => s.id === surfaceId)?.name ?? 'Surface';
            this.toast.info(`"${name}" is already attached to "${agent.name}"`);
            return;
        }
        this.assignSurfaceToAgent(surfaceId, agentId, category ? categoryToPlace(category) : 'all');
    }

    private assignSurfaceToAgent(surfaceId: number, agentId: number, place: AgentSurfacePlace): void {
        const agent = this.agents().find((a) => a.id === agentId);
        if (!agent) return;
        if (agent.default_surfaces.some((ds) => ds.surface === surfaceId && ds.place === place)) return;
        const next: AgentDefaultSurface[] = [...agent.default_surfaces, { surface: surfaceId, place }];
        this.patchAgentDefaultSurfaces(agentId, next);
    }

    moveSurfacePlace(surfaceId: number, agentId: number, category: SurfaceCategoryId): void {
        const agent = this.agents().find((a) => a.id === agentId);
        if (!agent) return;
        const place = categoryToPlace(category);
        const others = agent.default_surfaces.filter((ds) => ds.surface !== surfaceId);
        const next: AgentDefaultSurface[] = [...others, { surface: surfaceId, place }];
        this.patchAgentDefaultSurfaces(agentId, next);
    }

    detachSurfaceFromAgent(surfaceId: number, agentId: number): void {
        const agent = this.agents().find((a) => a.id === agentId);
        if (!agent) return;
        const next = agent.default_surfaces.filter((ds) => ds.surface !== surfaceId);
        this.patchAgentDefaultSurfaces(agentId, next, undefined, () => this.selectAgentSurfaces(agentId));
    }

    duplicateSurface(id: number): void {
        const src = this.surfaces().find((s) => s.id === id);
        if (!src) return;
        const existingNames = this.surfaces().map((s) => s.name);
        const ownerAgentId = src.owner_agent;
        // Only mirror the source's place when it actually has a default_surfaces
        // entry; otherwise leave the copy wherever the backend assigns it (don't
        // force a category from a missing entry).
        const srcPlace =
            ownerAgentId != null
                ? this.agents()
                      .find((a) => a.id === ownerAgentId)
                      ?.default_surfaces.find((ds) => ds.surface === src.id)?.place
                : undefined;
        const srcCategory = srcPlace != null ? placeToCategory(srcPlace) : null;
        this.createSurface(
            {
                name: computeUniqueCopyName(src.name, existingNames),
                description: src.description,
                instructions: src.instructions,
                owner_agent: src.owner_agent,
                allow_creation: src.allow_creation,
                python_tools: src.python_tools,
                mcp_tools: src.mcp_tools,
                storage_items: src.storage_items,
                knowledge: src.knowledge,
            },
            'Surface duplicated',
            ownerAgentId != null
                ? (created) =>
                      this.afterAgentSurfaceChange(ownerAgentId, () => {
                          if (srcCategory != null && srcCategory !== 'every-place') {
                              this.moveSurfacePlace(created.id, ownerAgentId, srcCategory);
                          }
                          this.selectAgentSurfaces(ownerAgentId);
                      })
                : undefined
        );
    }

    makeAgentSpecificCopy(surfaceId: number, agentId: number): void {
        const src = this.surfaces().find((s) => s.id === surfaceId);
        if (!src) return;
        const existingNames = this.surfaces().map((s) => s.name);
        this.createSurface(
            {
                name: computeUniqueCopyName(src.name, existingNames),
                description: src.description,
                instructions: src.instructions,
                owner_agent: agentId,
                allow_creation: src.allow_creation,
                python_tools: src.python_tools,
                mcp_tools: src.mcp_tools,
                storage_items: src.storage_items,
                knowledge: src.knowledge,
            },
            'Agent-specific copy created',
            () => this.afterAgentSurfaceChange(agentId, () => this.selectAgentSurfaces(agentId))
        );
    }

    saveNewSurface(body: CreateSurfaceRequest): void {
        this.createSurface({ ...body, owner_agent: null }, 'Surface created', (created) =>
            this.selectSurface(created.id)
        );
    }

    createSurfaceForAgent(
        agentId: number,
        body: CreateSurfaceRequest,
        category: SurfaceCategoryId = 'every-place'
    ): void {
        this.createSurface({ ...body, owner_agent: agentId }, 'Surface created', (created) =>
            this.afterAgentSurfaceChange(agentId, () => {
                if (category !== 'every-place') this.moveSurfacePlace(created.id, agentId, category);
            })
        );
    }

    private createSurface(body: CreateSurfaceRequest, successMsg: string, onCreated?: (s: Surface) => void): void {
        const trimmed = (body.name ?? '').trim();
        if (!trimmed) {
            this.toast.error('Surface name is required');
            return;
        }
        this.saving.set(true);
        this.surfacesApi.create({ ...body, name: trimmed }).subscribe({
            next: (created) => {
                this.surfaces.update((list) => [...list, created]);
                this.saving.set(false);
                onCreated?.(created);
                this.toast.success(successMsg);
            },
            error: (err) => {
                this.saving.set(false);
                this.toast.error(this.extractError(err, 'Failed to create surface'));
            },
        });
    }

    private patchAgentDefaultSurfaces(
        agentId: number,
        next: AgentDefaultSurface[],
        successMsg?: string,
        onDone?: () => void
    ): void {
        this.saving.set(true);
        this.agentsApi.partialUpdate(agentId, { default_surfaces: next }).subscribe({
            next: (updated) => {
                this.agents.update((list) => list.map((a) => (a.id === agentId ? updated : a)));
                this.saving.set(false);
                if (successMsg) this.toast.success(successMsg);
                onDone?.();
            },
            error: (err) => {
                this.saving.set(false);
                this.toast.error(this.extractError(err, 'Failed to update agent surfaces'));
            },
        });
    }

    private afterAgentSurfaceChange(agentId: number, onDone?: () => void): void {
        this.agentsApi.getById(agentId).subscribe({
            next: (agent) => {
                this.agents.update((list) => list.map((a) => (a.id === agentId ? agent : a)));
                onDone?.();
            },
            error: () => onDone?.(),
        });
    }

    saveNewAgent(body: CreateAgentDefinitionRequest): void {
        const trimmed = (body.name ?? '').trim();
        if (!trimmed) {
            this.toast.error('Agent name is required');
            return;
        }
        this.saving.set(true);
        this.agentsApi.create({ ...body, name: trimmed, instructions: body.instructions ?? '' }).subscribe({
            next: (created) => {
                this.agents.update((list) => [...list, created]);
                this.selectAgent(created.id);
                this.saving.set(false);
                this.toast.success('Agent created');
            },
            error: (err) => {
                this.saving.set(false);
                this.agentSaveErrorTick.update((n) => n + 1);
                this.toast.error(this.extractError(err, 'Failed to create agent'));
            },
        });
    }

    updateAgent(id: number, patch: PartialUpdateAgentDefinitionRequest): void {
        this.saving.set(true);
        this.agentsApi.partialUpdate(id, patch).subscribe({
            next: (updated) => {
                this.agents.update((list) => list.map((a) => (a.id === id ? updated : a)));
                this.saving.set(false);
            },
            error: (err) => {
                this.saving.set(false);
                this.agentSaveErrorTick.update((n) => n + 1);
                this.toast.error(this.extractError(err, 'Failed to save agent'));
            },
        });
    }

    updateSurface(id: number, patch: PartialUpdateSurfaceRequest): void {
        this.saving.set(true);
        this.surfacesApi.partialUpdate(id, patch).subscribe({
            next: (updated) => {
                this.surfaces.update((list) => list.map((s) => (s.id === id ? updated : s)));
                this.saving.set(false);
            },
            error: (err) => {
                this.saving.set(false);
                this.toast.error(this.extractError(err, 'Failed to save surface'));
            },
        });
    }

    duplicateAgent(id: number): void {
        const src = this.agents().find((a) => a.id === id);
        if (!src) return;
        const existingNames = this.agents().map((a) => a.name);
        this.saving.set(true);
        this.agentsApi.copy(src, computeUniqueCopyName(src.name, existingNames)).subscribe({
            next: (created) => {
                this.agents.update((list) => [...list, created]);
                this.selectAgent(created.id);
                this.saving.set(false);
                this.toast.success('Agent duplicated');
            },
            error: (err) => {
                this.saving.set(false);
                this.toast.error(this.extractError(err, 'Failed to duplicate agent'));
            },
        });
    }

    deleteAgent(id: number): void {
        this.saving.set(true);
        this.agentsApi.delete(id).subscribe({
            next: () => {
                this.agents.update((list) => list.filter((a) => a.id !== id));
                this.surfaces.update((list) => list.filter((s) => s.owner_agent !== id));
                const sel = this.selectedNode();
                if (sel.kind === 'agent' && sel.id === id) {
                    this.clearSelection();
                }
                this.saving.set(false);
                this.toast.success('Agent deleted');
            },
            error: (err) => {
                this.saving.set(false);
                this.toast.error(this.extractError(err, 'Failed to delete agent'));
            },
        });
    }

    deleteSurface(id: number): void {
        this.saving.set(true);
        this.surfacesApi.delete(id).subscribe({
            next: () => {
                this.surfaces.update((list) => list.filter((s) => s.id !== id));
                this.agents.update((list) =>
                    list.map((a) =>
                        a.default_surfaces.some((ds) => ds.surface === id)
                            ? { ...a, default_surfaces: a.default_surfaces.filter((ds) => ds.surface !== id) }
                            : a
                    )
                );
                const sel = this.selectedNode();
                if (sel.kind === 'surface' && sel.id === id) {
                    this.clearSelection();
                }
                this.saving.set(false);
                this.toast.success('Surface deleted');
            },
            error: (err) => {
                this.saving.set(false);
                this.toast.error(this.extractError(err, 'Failed to delete surface'));
            },
        });
    }

    private extractError(err: unknown, fallback: string): string {
        const e = err as { error?: Record<string, unknown> };
        const body = e?.error;
        if (!body) return fallback;
        if (typeof body === 'string') return body;
        if (typeof body['detail'] === 'string') return body['detail'] as string;
        for (const v of Object.values(body)) {
            if (typeof v === 'string') return v;
            if (Array.isArray(v) && typeof v[0] === 'string') return v[0] as string;
        }
        return fallback;
    }
}
