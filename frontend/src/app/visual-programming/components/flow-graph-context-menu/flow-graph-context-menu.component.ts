import { FlexibleConnectedPositionStrategy, Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    afterNextRender,
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
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
import { IPoint } from '@foblex/2d';
import { Subscription } from 'rxjs';

import {
    CONTEXT_MENU_TAB,
    ContextMenuTab,
    FLOW_GRAPH_CONTEXT_MENU_ITEMS,
    FLOW_GRAPH_CONTEXT_MENU_POSITIONS,
} from '../../core/constants/flow-graph-context-menu.constants';
import { CreateNodeRequest } from '../../core/models/node-creation.types';
import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu/flow-graph-core-menu.component';
import { FlowsMenuComponent } from './flows-menu/flows-menu.component';
import { FlowProjectsContextMenuComponent } from './section-projects/section-projects.component';

export type { ContextMenuTab };

@Component({
    selector: 'app-flow-graph-context-menu',
    standalone: true,
    templateUrl: './flow-graph-context-menu.component.html',
    styleUrls: ['./flow-graph-context-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [FlowGraphCoreMenuComponent, FlowProjectsContextMenuComponent, FlowsMenuComponent],
})
export class FlowGraphContextMenuComponent implements AfterViewInit {
    public readonly position = input.required<IPoint>();
    public readonly currentFlowId = input<number | null>(null);
    public readonly nodeSelected = output<CreateNodeRequest>();
    public readonly closed = output<void>();

    @ViewChild('menuTemplate', { static: true })
    private menuTemplate!: TemplateRef<unknown>;

    public readonly searchTerm = signal('');
    public readonly selectedMenu = signal<ContextMenuTab>(CONTEXT_MENU_TAB.FLOW_CORE);
    public readonly menuTab = CONTEXT_MENU_TAB;
    public readonly menuItems = FLOW_GRAPH_CONTEXT_MENU_ITEMS;
    public readonly viewportMargin = 16;
    public readonly overlayPositions = FLOW_GRAPH_CONTEXT_MENU_POSITIONS;

    private readonly overlay = inject(Overlay);
    private readonly injector = inject(Injector);
    private readonly viewContainerRef = inject(ViewContainerRef);

    private overlayRef?: OverlayRef;
    private backdropSub?: Subscription;

    public ngAfterViewInit(): void {
        this.createOverlay();
        this.initializeEffects();
    }

    public ngOnDestroy(): void {
        this.backdropSub?.unsubscribe();
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

        this.backdropSub = this.overlayRef.backdropClick().subscribe(() => this.closed.emit());
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
