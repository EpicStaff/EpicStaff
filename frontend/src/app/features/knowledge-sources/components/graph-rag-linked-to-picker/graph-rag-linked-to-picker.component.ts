import { CdkTrapFocus } from '@angular/cdk/a11y';
import { CdkConnectedOverlay, CdkOverlayOrigin, Overlay } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, LoadingSpinnerComponent, SearchComponent } from '@shared/components';
import { EMPTY, Subject } from 'rxjs';
import { catchError, debounceTime, groupBy, mergeMap, switchMap, tap } from 'rxjs/operators';

import { GRAPH_SEARCH_DEBOUNCE_MS, GRAPH_SEARCH_MAX_LENGTH } from '../../constants/constants';
import { GraphRagService } from '../../services/graph-rag.service';
import {
    LINKED_TO_PICKER_PAGE_SIZE,
    LINKED_TO_TARGET_TABS,
    LinkedToTargetType,
    pickLinkedToRowLabel,
} from './linked-to-targets';

/** Scroll within this many px of the bottom triggers the next page load. */
const SCROLL_LOAD_MORE_THRESHOLD_PX = 64;

/** Overlay anchoring: start-aligned below the trigger, flipping above when there's no room. */
const OVERLAY_POSITIONS = [
    {
        originX: 'start' as const,
        originY: 'bottom' as const,
        overlayX: 'start' as const,
        overlayY: 'top' as const,
        offsetY: 4,
    },
    {
        originX: 'start' as const,
        originY: 'top' as const,
        overlayX: 'start' as const,
        overlayY: 'bottom' as const,
        offsetY: -4,
    },
];

interface PickerRow {
    id: string;
    label: string;
}

/** Per-tab UI state: load status, current search term, current page and loaded rows. */
interface TabState {
    status: 'idle' | 'loading' | 'ready' | 'error';
    searchTerm: string;
    page: number;
    total: number;
    rows: PickerRow[];
    /** Rows currently shown; the latest search term may still be in flight. */
    hasMore: boolean;
    errorMessage: string;
}

export interface LinkedToSelection {
    type: LinkedToTargetType;
    id: string;
}

const EMPTY_STATE: TabState = {
    status: 'idle',
    searchTerm: '',
    page: 1,
    total: 0,
    rows: [],
    hasMore: false,
    errorMessage: '',
};

@Component({
    selector: 'app-graph-rag-linked-to-picker',
    templateUrl: './graph-rag-linked-to-picker.component.html',
    styleUrls: ['./graph-rag-linked-to-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppSvgIconComponent,
        CdkConnectedOverlay,
        CdkOverlayOrigin,
        CdkTrapFocus,
        LoadingSpinnerComponent,
        SearchComponent,
    ],
})
export class GraphRagLinkedToPickerComponent {
    // 1. Inputs / Outputs
    readonly ragId = input.required<number>();
    /**
     * Allowed target-table names for the current subject table. The picker only shows tabs whose
     * `type` is in this list; the parent wraps the trigger in `@if (allowedTargets().length)` so an
     * empty list hides the picker entirely.
     */
    readonly allowedTargets = input<readonly LinkedToTargetType[]>([]);
    readonly picked = output<LinkedToSelection>();

    // 3. Signals & Computed
    readonly isOpen = signal(false);
    readonly visibleTabs = computed(() => {
        const allowed = new Set<LinkedToTargetType>(this.allowedTargets());
        return LINKED_TO_TARGET_TABS.filter((tab) => allowed.has(tab.type));
    });
    readonly activeTab = signal<LinkedToTargetType>(LINKED_TO_TARGET_TABS[0].type);
    readonly searchMaxLength = GRAPH_SEARCH_MAX_LENGTH;

    /** The per-tab state map; a tab's entry is created lazily on first open. */
    private readonly states = signal<Partial<Record<LinkedToTargetType, TabState>>>({});

    readonly activeState = computed<TabState>(() => this.states()[this.activeTab()] ?? EMPTY_STATE);

    // 5. Public template-bound
    protected readonly overlayPositions = OVERLAY_POSITIONS;

    // 6. Private fields
    private readonly overlay = inject(Overlay);
    protected readonly scrollStrategy = this.overlay.scrollStrategies.reposition();
    private readonly graphRagService = inject(GraphRagService);
    private readonly destroyRef = inject(DestroyRef);
    /** Each load request carries the tab and page it is for; late responses for a stale tab or page are dropped. */
    private readonly loadSubject = new Subject<{ type: LinkedToTargetType; append: boolean }>();
    /** Debounced search; the handler resets the tab's page and rows and triggers a fresh load. */
    private readonly searchSubject = new Subject<{ type: LinkedToTargetType; term: string }>();
    /** rAF handle for scroll throttling; we service at most one check per animation frame. */
    private scrollFrame = 0;

    constructor() {
        this.initLoadPipeline();
        this.initSearchDebounce();
    }

    // 9. Public methods
    toggle(): void {
        if (this.isOpen()) {
            this.close();
        } else {
            this.open();
        }
    }

    close(): void {
        this.isOpen.set(false);
    }

    selectTab(type: LinkedToTargetType): void {
        if (this.activeTab() === type) return;
        this.activeTab.set(type);
        this.ensureTabLoaded(type);
    }

    onSearchInput(term: string): void {
        // Reflect the typed term immediately so the input does not snap back between keystrokes;
        // the debounced stream handles the actual backend fetch.
        const type = this.activeTab();
        const current = this.states()[type];
        if (!current || current.searchTerm !== term) {
            this.updateState(type, { searchTerm: term });
        }
        this.searchSubject.next({ type, term });
    }

    loadMore(): void {
        const type = this.activeTab();
        const state = this.states()[type];
        if (!state || state.status === 'loading' || !state.hasMore) return;
        // Flip to `loading` synchronously so the next scroll event (fired many times per
        // drag) bails out at the guard above. Without this a single scroll would bump
        // page and emit a request on every event — switchMap would cancel all but the
        // last, but the UI still issues the storm visible in the network panel.
        this.updateState(type, { status: 'loading', page: state.page + 1 });
        this.loadSubject.next({ type, append: true });
    }

    /**
     * Trigger the next page once the user scrolls within SCROLL_LOAD_MORE_THRESHOLD_PX
     * of the bottom. Scroll fires many times per drag, so we collapse all events within
     * one animation frame into a single near-bottom check — the `loadMore` guard then
     * drops any in-flight duplicate.
     */
    onListScroll(event: Event): void {
        const target = event.target as HTMLElement;
        if (this.scrollFrame !== 0) return;
        this.scrollFrame = requestAnimationFrame(() => {
            this.scrollFrame = 0;
            const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight;
            if (distanceFromBottom <= SCROLL_LOAD_MORE_THRESHOLD_PX) {
                this.loadMore();
            }
        });
    }

    pick(row: PickerRow): void {
        this.picked.emit({ type: this.activeTab(), id: row.id });
        this.close();
    }

    // 10. Private methods
    private open(): void {
        // If the currently active tab is no longer in the allowed set, switch to the first allowed tab
        // before the overlay opens — otherwise the body would show rows for a tab whose button is hidden.
        const visible = this.visibleTabs();
        if (visible.length > 0 && !visible.some((tab) => tab.type === this.activeTab())) {
            this.activeTab.set(visible[0].type);
        }
        this.isOpen.set(true);
        this.ensureTabLoaded(this.activeTab());
    }

    private ensureTabLoaded(type: LinkedToTargetType): void {
        const state = this.states()[type];
        if (state && state.status !== 'idle') return;
        this.updateState(type, { status: 'loading', page: 1, rows: [], total: 0, hasMore: false });
        this.loadSubject.next({ type, append: false });
    }

    private initSearchDebounce(): void {
        this.searchSubject
            .pipe(
                debounceTime(GRAPH_SEARCH_DEBOUNCE_MS),
                tap(({ type, term }) => {
                    // Reset the tab's paging and rows for the new query; the load pipeline fetches page 1.
                    this.updateState(type, {
                        searchTerm: term,
                        page: 1,
                        rows: [],
                        total: 0,
                        hasMore: false,
                        status: 'loading',
                        errorMessage: '',
                    });
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(({ type }) => this.loadSubject.next({ type, append: false }));
    }

    private initLoadPipeline(): void {
        // Per-tab cancellation: group by tab so a late response for "a" cannot overwrite the
        // "ab" result for the same tab, while a load for a different tab is unaffected. Within a tab
        // switchMap cancels the stale fetch; across tabs mergeMap runs them concurrently.
        this.loadSubject
            .pipe(
                groupBy((request) => request.type),
                mergeMap((group) =>
                    group.pipe(
                        switchMap(({ type, append }) => {
                            const state = this.states()[type] ?? { ...EMPTY_STATE };
                            const page = state.page;
                            const searchTerm = state.searchTerm.trim() || undefined;
                            return this.graphRagService
                                .getTableData({
                                    ragId: this.ragId(),
                                    tableName: type,
                                    page,
                                    pageSize: LINKED_TO_PICKER_PAGE_SIZE,
                                    search: searchTerm,
                                    searchScope: 'identity',
                                })
                                .pipe(
                                    tap((data) => {
                                        const current = this.states()[type];
                                        const existingRows = append && current ? current.rows : [];
                                        const mappedRows = data.rows.map((row) => ({
                                            id: String(row['id'] ?? ''),
                                            label: pickLinkedToRowLabel(type, row),
                                        }));
                                        const rows = [...existingRows, ...mappedRows];
                                        this.updateState(type, {
                                            status: 'ready',
                                            total: data.total,
                                            rows,
                                            hasMore: rows.length < data.total,
                                            errorMessage: '',
                                        });
                                    }),
                                    catchError((error: HttpErrorResponse) => {
                                        this.updateState(type, {
                                            status: 'error',
                                            errorMessage: `Failed to load ${type} (${error.status || 'network'})`,
                                        });
                                        return EMPTY;
                                    })
                                );
                        })
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    private updateState(type: LinkedToTargetType, patch: Partial<TabState>): void {
        this.states.update((states) => {
            const current = states[type] ?? { ...EMPTY_STATE };
            return { ...states, [type]: { ...current, ...patch } };
        });
    }
}
