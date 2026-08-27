import { CdkDragDrop, DragDropModule } from '@angular/cdk/drag-drop';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    inject,
    input,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
    AppSvgIconComponent,
    HelpTooltipComponent,
    SelectDropdownComponent,
    SelectDropdownListItem,
    SelectDropdownTriggerDirective,
} from '@shared/components';
import { CollapseOnOverflowDirective, EnterBlurDirective } from '@shared/directives';
import { computeUniqueName } from '@shared/utils';

import { AgentDefaultSurface, AgentSurfacePlace } from '../../../../../models/agent-definition.model';
import {
    CreateSurfaceRequest,
    PartialUpdateSurfaceRequest,
    Surface,
    SurfaceSaveError,
} from '../../../../../models/surface.model';
import { SurfaceTabId } from '../../../../../models/surface-card.model';
import {
    categoryToPlace,
    placeToCategory,
    SURFACE_CATEGORIES,
    SurfaceCategoryConfig,
    SurfaceCategoryId,
} from '../../../../../models/surface-category.model';
import { SurfaceDragService } from '../../../../../services/surface-drag.service';
import { SurfaceCardComponent } from './surface-card/surface-card.component';

@Component({
    selector: 'app-agent-surfaces-panel',
    imports: [
        FormsModule,
        EnterBlurDirective,
        AppSvgIconComponent,
        SurfaceCardComponent,
        DragDropModule,
        SelectDropdownComponent,
        SelectDropdownTriggerDirective,
        CollapseOnOverflowDirective,
        HelpTooltipComponent,
    ],
    templateUrl: './agent-surfaces-panel.component.html',
    styleUrls: ['./agent-surfaces-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentSurfacesPanelComponent {
    private readonly surfaceDrag = inject(SurfaceDragService);

    surfaces = input<Surface[]>([]);
    agentId = input<number | null>(null);
    /** The owning AgentDefinition's llm_config — forwarded to each surface card's
     * RAG panel so suggested-params requests know which LLM's context window to use. */
    llmConfigId = input<number | null>(null);
    defaultSurfaces = input<AgentDefaultSurface[]>([]);
    sharedSurfaceIds = input<ReadonlySet<number>>(new Set<number>());
    saving = input<boolean>(false);
    /** Last surface-save failure from the store; forwarded to each card for per-id revert. */
    saveError = input<SurfaceSaveError | null>(null);
    /** Bumped by the store when a surface CREATE fails, so the draft is kept for retry. */
    surfaceCreateErrorTick = input<number>(0);

    readonly createSurface = output<{ body: CreateSurfaceRequest; place: SurfaceCategoryId }>();
    readonly addFromShared = output<{ surfaceId: number; category: SurfaceCategoryId }>();
    readonly dropSharedSurface = output<{ surfaceId: number; category: SurfaceCategoryId }>();
    readonly setSurfacePlaces = output<{ surfaceId: number; places: AgentSurfacePlace[] }>();
    readonly makeSharedSurface = output<number>();
    readonly detachSurface = output<number>();
    readonly deleteSurface = output<number>();
    readonly duplicateSurface = output<number>();
    readonly makeAgentSpecificCopy = output<number>();
    readonly openSource = output<number>();
    readonly renameSurface = output<{ id: number; name: string }>();
    readonly surfaceChange = output<{ id: number; patch: PartialUpdateSurfaceRequest }>();
    readonly viewSummary = output<{ place: SurfaceCategoryId; surfaceIds: number[] }>();

    readonly categories = SURFACE_CATEGORIES;
    readonly searchQuery = signal('');
    readonly expandedSurfaceId = signal<number | null>(null);
    private readonly activeTabBySurfaceId = signal<ReadonlyMap<number, SurfaceTabId>>(new Map());
    readonly dragging = signal<boolean>(false);
    readonly draftCategoryId = signal<SurfaceCategoryId | null>(null);
    readonly draftName = signal<string>('');
    // Guards against a burst of draft-content changes POSTing the surface more than once.
    private draftMaterializing = false;
    private lastCreateErrorTick = 0;

    private readonly knownSurfaceIdsBeforeCreate = signal<Set<number> | null>(null);

    constructor() {
        // Success: a newly-created surface appeared → swap the draft for it (drop the draft,
        // open the real one).
        effect(() => {
            const known = this.knownSurfaceIdsBeforeCreate();
            if (!known) return;
            const created = this.surfaces().find((s) => !known.has(s.id));
            if (!created) return;
            this.knownSurfaceIdsBeforeCreate.set(null);
            this.draftMaterializing = false;
            const draftTab = this.draftSurfaceCard()?.activeTab();
            this.cancelDraft();
            this.expandedSurfaceId.set(created.id);
            if (draftTab) this.onCardActiveTabChange(created, draftTab);
        });

        // Error: a create failed → keep the draft mounted and re-enable retry.
        effect(() => {
            const tick = this.surfaceCreateErrorTick();
            untracked(() => {
                if (tick === this.lastCreateErrorTick) return;
                this.lastCreateErrorTick = tick;
                this.draftMaterializing = false;
                this.knownSurfaceIdsBeforeCreate.set(null);
            });
        });
    }

    private readonly surfaceById = computed<Map<number, Surface>>(() => new Map(this.surfaces().map((s) => [s.id, s])));

    readonly surfacesByCategory = computed<Map<SurfaceCategoryId, Surface[]>>(() => {
        const q = this.searchQuery().trim().toLowerCase();
        const byId = this.surfaceById();
        const result = new Map<SurfaceCategoryId, Surface[]>(this.categories.map((c) => [c.id, []]));
        const seenByCategory = new Map<SurfaceCategoryId, Set<number>>(
            this.categories.map((c) => [c.id, new Set<number>()])
        );

        for (const ds of this.defaultSurfaces()) {
            const categoryId = placeToCategory(ds.place);
            const seen = seenByCategory.get(categoryId);
            if (!seen || seen.has(ds.surface)) continue;

            const surface = byId.get(ds.surface);
            if (!surface) continue;
            if (q && !surface.name.toLowerCase().includes(q)) continue;

            seen.add(ds.surface);
            result.get(categoryId)!.push(surface);
        }

        return result;
    });

    // ---- shared surface drop from the sidebar tree ----
    readonly sharedDropCategoryId = signal<SurfaceCategoryId | null>(null);

    onSharedDragOver(event: DragEvent, category: SurfaceCategoryId): void {
        if (!this.surfaceDrag.isDragging()) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        this.sharedDropCategoryId.set(category);
    }

    onSharedDragLeave(event: DragEvent, category: SurfaceCategoryId): void {
        const host = event.currentTarget as HTMLElement;
        const related = event.relatedTarget as Node | null;
        if (related && host.contains(related)) return;
        if (this.sharedDropCategoryId() === category) this.sharedDropCategoryId.set(null);
    }

    onSharedDrop(event: DragEvent, category: SurfaceCategoryId): void {
        this.sharedDropCategoryId.set(null);
        const dragged = this.surfaceDrag.dragged();
        if (!dragged) return;
        event.preventDefault();
        this.surfaceDrag.end();
        this.dropSharedSurface.emit({ surfaceId: dragged.id, category });
    }

    placesForSurface(surfaceId: number): AgentSurfacePlace[] {
        return this.defaultSurfaces()
            .filter((ds) => ds.surface === surfaceId)
            .map((ds) => ds.place);
    }

    // Move-instance DnD with invariant guardrails: dropping into Every-Place collapses to
    // ['all']; dragging out of Every-Place replaces 'all' with the target concrete; otherwise
    // the source place is removed and the target added.
    onSurfaceDropped(event: CdkDragDrop<SurfaceCategoryId>, target: SurfaceCategoryId): void {
        const surface = event.item.data as Surface;
        if (event.previousContainer === event.container) return;
        const from = event.previousContainer.data;
        let next: AgentSurfacePlace[];
        if (target === 'every-place') {
            next = ['all'];
        } else if (from === 'every-place') {
            next = [categoryToPlace(target)];
        } else {
            const fromPlace = categoryToPlace(from);
            const targetPlace = categoryToPlace(target);
            const kept = this.placesForSurface(surface.id).filter((p) => p !== fromPlace && p !== 'all');
            next = kept.includes(targetPlace) ? kept : [...kept, targetPlace];
        }
        this.setSurfacePlaces.emit({ surfaceId: surface.id, places: next });
    }

    onViewSummary(category: SurfaceCategoryId): void {
        const surfaceIds = (this.surfacesByCategory().get(category) ?? []).map((s) => s.id);
        if (surfaceIds.length) this.viewSummary.emit({ place: category, surfaceIds });
    }

    isShared(surface: Surface): boolean {
        return this.sharedSurfaceIds().has(surface.id);
    }

    // Per-category "Add From Shared" list. Concrete blocks exclude a surface that already
    // has that place or 'all'; Every-Place excludes anything assigned at all (so we never
    // create an 'all'+concrete combination).
    addableSharedFor(category: SurfaceCategoryId): SelectDropdownListItem<number>[] {
        const shared = this.sharedSurfaceIds();
        const targetPlace = categoryToPlace(category);
        return this.surfaces()
            .filter((s) => {
                if (!shared.has(s.id)) return false;
                const rows = this.placesForSurface(s.id);
                if (category === 'every-place') return rows.length === 0;
                return !rows.some((p) => p === targetPlace || p === 'all');
            })
            .map((s) => ({ name: s.name, value: s.id }));
    }

    onAddFromShared(values: unknown[], category: SurfaceCategoryId): void {
        const id = values[0] as number | undefined;
        if (id != null) this.addFromShared.emit({ surfaceId: id, category });
    }

    onDragStarted(): void {
        window.getSelection()?.removeAllRanges();
        this.dragging.set(true);
    }

    isExpanded(surface: Surface): boolean {
        return this.expandedSurfaceId() === surface.id;
    }

    onCardExpanded(surface: Surface, expanded: boolean): void {
        this.knownSurfaceIdsBeforeCreate.set(null);
        this.draftCategoryId.set(null);
        this.expandedSurfaceId.set(expanded ? surface.id : null);
    }

    activeTabFor(surface: Surface): SurfaceTabId {
        return this.activeTabBySurfaceId().get(surface.id) ?? 'tools';
    }

    onCardActiveTabChange(surface: Surface, tab: SurfaceTabId): void {
        this.activeTabBySurfaceId.update((map) => new Map(map).set(surface.id, tab));
    }

    private readonly draftSurfaceCard = viewChild('draftSurfaceCard', { read: SurfaceCardComponent });

    isDrafting(categoryId: SurfaceCategoryId): boolean {
        return this.draftCategoryId() === categoryId;
    }

    startCreateSurface(categoryId: SurfaceCategoryId): void {
        this.knownSurfaceIdsBeforeCreate.set(null);
        this.expandedSurfaceId.set(null);
        this.draftName.set('');
        this.draftMaterializing = false;
        this.draftCategoryId.set(categoryId);
    }

    cancelDraft(): void {
        this.draftCategoryId.set(null);
        this.draftName.set('');
    }

    saveDraft(): void {
        const name = this.draftName().trim();
        if (!name) return;
        this.materializeDraft(name);
    }

    onDraftContentChanged(): void {
        const name = this.draftName().trim() || this.defaultSurfaceName();
        this.materializeDraft(name);
    }

    private materializeDraft(name: string): void {
        if (this.draftMaterializing) return;
        const place = this.draftCategoryId();
        const card = this.draftSurfaceCard();
        if (!place || !card) return;
        this.draftMaterializing = true;
        this.knownSurfaceIdsBeforeCreate.set(new Set(this.surfaces().map((s) => s.id)));
        this.createSurface.emit({ body: card.buildCreateRequest(name), place });
    }

    private defaultSurfaceName(): string {
        return computeUniqueName(
            'Untitled Surface',
            this.surfaces().map((s) => s.name)
        );
    }

    categoryTrackBy(_index: number, category: SurfaceCategoryConfig): SurfaceCategoryId {
        return category.id;
    }

    surfaceTrackBy(_index: number, surface: Surface): number {
        return surface.id;
    }
}
