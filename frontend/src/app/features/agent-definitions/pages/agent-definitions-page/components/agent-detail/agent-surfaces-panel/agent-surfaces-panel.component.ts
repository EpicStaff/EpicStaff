import { CdkDragDrop, DragDropModule } from '@angular/cdk/drag-drop';
import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
    AppSvgIconComponent,
    SelectDropdownComponent,
    SelectDropdownListItem,
    SelectDropdownTriggerDirective,
} from '@shared/components';
import { EnterBlurDirective } from '@shared/directives';

import { AgentDefaultSurface } from '../../../../../models/agent-definition.model';
import { CreateSurfaceRequest, PartialUpdateSurfaceRequest, Surface } from '../../../../../models/surface.model';
import {
    placeToCategory,
    SURFACE_CATEGORIES,
    SurfaceCategoryConfig,
    SurfaceCategoryId,
} from '../../../../../models/surface-category.model';
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
    ],
    templateUrl: './agent-surfaces-panel.component.html',
    styleUrls: ['./agent-surfaces-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentSurfacesPanelComponent {
    surfaces = input<Surface[]>([]);
    agentId = input<number | null>(null);
    defaultSurfaces = input<AgentDefaultSurface[]>([]);
    sharedSurfaceIds = input<ReadonlySet<number>>(new Set<number>());

    readonly createSurface = output<{ body: CreateSurfaceRequest; place: SurfaceCategoryId }>();
    readonly addFromShared = output<number>();
    readonly moveSurfacePlace = output<{ id: number; place: SurfaceCategoryId }>();
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
    readonly draftCategoryId = signal<SurfaceCategoryId | null>(null);
    readonly draftName = signal<string>('');

    private readonly knownSurfaceIdsBeforeCreate = signal<Set<number> | null>(null);

    constructor() {
        effect(() => {
            const known = this.knownSurfaceIdsBeforeCreate();
            if (!known) return;
            const created = this.surfaces().find((s) => !known.has(s.id));
            if (!created) return;
            this.expandedSurfaceId.set(created.id);
            this.knownSurfaceIdsBeforeCreate.set(null);
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

    onSurfaceDropped(event: CdkDragDrop<SurfaceCategoryId>, target: SurfaceCategoryId): void {
        const surface = event.item.data as Surface;
        if (event.previousContainer === event.container) return;
        this.moveSurfacePlace.emit({ id: surface.id, place: target });
    }

    onViewSummary(category: SurfaceCategoryId): void {
        const surfaceIds = (this.surfacesByCategory().get(category) ?? []).map((s) => s.id);
        if (surfaceIds.length) this.viewSummary.emit({ place: category, surfaceIds });
    }

    isShared(surface: Surface): boolean {
        return this.sharedSurfaceIds().has(surface.id);
    }

    readonly addableSharedItems = computed<SelectDropdownListItem<number>[]>(() => {
        const shared = this.sharedSurfaceIds();
        const assigned = new Set(this.defaultSurfaces().map((ds) => ds.surface));
        return this.surfaces()
            .filter((s) => shared.has(s.id) && !assigned.has(s.id))
            .map((s) => ({ name: s.name, value: s.id }));
    });

    onAddFromShared(values: unknown[]): void {
        const id = values[0] as number | undefined;
        if (id != null) this.addFromShared.emit(id);
    }

    isExpanded(surface: Surface): boolean {
        return this.expandedSurfaceId() === surface.id;
    }

    onCardExpanded(surface: Surface, expanded: boolean): void {
        this.knownSurfaceIdsBeforeCreate.set(null);
        this.draftCategoryId.set(null);
        this.expandedSurfaceId.set(expanded ? surface.id : null);
    }

    private readonly draftSurfaceCard = viewChild('draftSurfaceCard', { read: SurfaceCardComponent });

    isDrafting(categoryId: SurfaceCategoryId): boolean {
        return this.draftCategoryId() === categoryId;
    }

    startCreateSurface(categoryId: SurfaceCategoryId): void {
        this.knownSurfaceIdsBeforeCreate.set(null);
        this.expandedSurfaceId.set(null);
        this.draftName.set('');
        this.draftCategoryId.set(categoryId);
    }

    cancelDraft(): void {
        this.draftCategoryId.set(null);
        this.draftName.set('');
    }

    saveDraft(): void {
        const name = this.draftName().trim();
        const place = this.draftCategoryId();
        const card = this.draftSurfaceCard();
        if (!name || !place || !card) return;
        this.knownSurfaceIdsBeforeCreate.set(new Set(this.surfaces().map((s) => s.id)));
        this.createSurface.emit({ body: card.buildCreateRequest(name), place });
        this.cancelDraft();
    }

    categoryTrackBy(_index: number, category: SurfaceCategoryConfig): SurfaceCategoryId {
        return category.id;
    }

    surfaceTrackBy(_index: number, surface: Surface): number {
        return surface.id;
    }
}
