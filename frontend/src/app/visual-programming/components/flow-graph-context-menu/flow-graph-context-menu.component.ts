import { FlexibleConnectedPositionStrategy, Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    afterNextRender,
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    Injector,
    input,
    output,
    signal,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { IPoint } from '@foblex/2d';
import { filter } from 'rxjs';

import { GetGraphLightRequest } from '../../../features/flows/models/graph.model';
import {
    CONTEXT_MENU_TAB,
    ContextMenuTab,
    FLOW_GRAPH_CONTEXT_MENU_ITEMS,
    FLOW_GRAPH_CONTEXT_MENU_POSITIONS,
} from '../../core/constants/flow-graph-context-menu.constants';
import { CreateNodeRequest } from '../../core/models/node-creation.types';
import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu/flow-graph-core-menu.component';
import { FlowsMenuComponent } from './flows-menu/flows-menu.component';

export type { ContextMenuTab };

@Component({
    selector: 'app-flow-graph-context-menu',
    templateUrl: './flow-graph-context-menu.component.html',
    styleUrls: ['./flow-graph-context-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [FlowGraphCoreMenuComponent, FlowsMenuComponent],
})
export class FlowGraphContextMenuComponent implements AfterViewInit {
    public readonly position = input.required<IPoint>();
    public readonly currentFlowId = input<number | null>(null);
    public readonly availableFlows = input<GetGraphLightRequest[]>([]);
    public readonly nodeSelected = output<CreateNodeRequest>();
    public readonly closed = output<void>();

    @ViewChild('menuTemplate', { static: true })
    private menuTemplate!: TemplateRef<unknown>;

    public readonly searchTerm = signal('');
    public readonly selectedMenu = signal<ContextMenuTab>(CONTEXT_MENU_TAB.FLOW_CORE);
    protected readonly otherFlows = computed(() =>
        this.availableFlows().filter((flow) => flow.id !== this.currentFlowId())
    );
    protected readonly visibleTabs = computed(() =>
        FLOW_GRAPH_CONTEXT_MENU_ITEMS.filter(
            (item) => item.type !== CONTEXT_MENU_TAB.FLOWS || this.otherFlows().length > 0
        )
    );
    public readonly menuTab = CONTEXT_MENU_TAB;
    public readonly viewportMargin = 16;
    public readonly overlayPositions = FLOW_GRAPH_CONTEXT_MENU_POSITIONS;

    private readonly overlay = inject(Overlay);
    private readonly injector = inject(Injector);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private readonly destroyRef = inject(DestroyRef);

    private overlayRef?: OverlayRef;

    public ngAfterViewInit(): void {
        this.createOverlay();
        this.initializeEffects();
    }

    public ngOnDestroy(): void {
        this.overlayRef?.dispose();
    }

    public onSelectMenu(type: ContextMenuTab): void {
        this.selectedMenu.set(type);
    }

    public onSearchInput(event: Event): void {
        const input = event.target as HTMLInputElement;
        this.searchTerm.set(input.value);
    }

    public onNodeSelected(event: CreateNodeRequest): void {
        this.nodeSelected.emit(event);
    }

    private createOverlay(): void {
        this.overlayRef = this.overlay.create({
            positionStrategy: this.createPositionStrategy(this.position()),
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            disposeOnNavigation: true,
            hasBackdrop: true,
            backdropClass: 'cdk-overlay-transparent-backdrop',
        });

        this.overlayRef
            .backdropClick()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.closed.emit());
        this.overlayRef
            .keydownEvents()
            .pipe(
                filter((event) => event.key === 'Escape'),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((event) => {
                // Esc belongs to the topmost layer: keep it from also reaching the window-level
                // ShortcutListenerDirective (canvas multi-select reset, node side panel save-and-close).
                event.stopPropagation();
                this.closed.emit();
            });
        this.overlayRef.attach(new TemplatePortal(this.menuTemplate, this.viewContainerRef));
    }

    private createPositionStrategy(position: IPoint): FlexibleConnectedPositionStrategy {
        return this.overlay
            .position()
            .flexibleConnectedTo({
                x: position.x,
                y: position.y,
                width: 0,
                height: 0,
            })
            .withPositions([...this.overlayPositions])
            .withPush(true)
            .withViewportMargin(this.viewportMargin);
    }

    private initializeEffects(): void {
        effect(
            () => {
                const position = this.position();
                if (!this.overlayRef) {
                    return;
                }

                this.overlayRef.updatePositionStrategy(this.createPositionStrategy(position));
                this.overlayRef.updatePosition();
            },
            { injector: this.injector }
        );

        effect(
            () => {
                this.selectedMenu();
                this.searchTerm();
                this.visibleTabs();

                if (!this.overlayRef) {
                    return;
                }

                afterNextRender(() => this.overlayRef?.updatePosition(), {
                    injector: this.injector,
                });
            },
            { injector: this.injector }
        );
    }
}
