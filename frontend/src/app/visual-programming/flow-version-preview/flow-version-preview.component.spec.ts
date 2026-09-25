import { Dialog } from '@angular/cdk/dialog';
import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { FDragStartedEvent } from '@foblex/flow';
import { NodeType } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { GraphVersionDto, RestoreWarning } from '../../features/flows/models/graph.model';
import {
    GraphVersionSnapshot,
    PreviewGraphVersionResponse,
} from '../../features/flows/models/graph-version-preview.model';
import { FlowsApiService } from '../../features/flows/services/flows-api.service';
import { ToastService } from '../../services/notifications';
import { FlowGraphComponent } from '../flow-graph/flow-graph.component';
import { ClipboardService } from '../services/clipboard.service';
import { FlowService } from '../services/flow.service';
import { NodeFactoryService } from '../services/node-factory.service';
import { NodeNameValidatorService } from '../services/node-name-validator.service';
import { SidePanelService } from '../services/side-panel.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { UniqueNodeNameValidatorService } from '../services/unique-node-name.validator';
import { FlowVersionPreviewComponent } from './flow-version-preview.component';

const EDITOR_SERVICES: Type<unknown>[] = [
    FlowService,
    UndoRedoService,
    SidePanelService,
    ClipboardService,
    NodeFactoryService,
    NodeNameValidatorService,
    UniqueNodeNameValidatorService,
];

function version(id: number): GraphVersionDto {
    return { id, graph_id: 1, name: `Version ${id}`, description: '', created_at: '2026-01-01T00:00:00Z' };
}

/** A snapshot with a Start node and one Python node named after the version. */
function snapshotFor(pythonNodeName: string): GraphVersionSnapshot {
    return {
        nodes: [
            { id: 1, node_type: 'StartNode', node_name: '__start__', variables: {}, metadata: {} },
            {
                id: 2,
                node_type: 'PythonNode',
                node_name: pythonNodeName,
                metadata: {},
                input_map: {},
                output_variable_path: null,
                test_input: {},
                python_code: { code: 'def main(): pass', entrypoint: 'main', libraries: '' },
            },
        ],
        edge_list: [],
    };
}

/** Spies on every method of a root service instance. */
function spyOnAllMethods(service: object): ReturnType<typeof vi.spyOn>[] {
    const prototype = Object.getPrototypeOf(service) as object;
    return Object.getOwnPropertyNames(prototype)
        .filter((name) => name !== 'constructor')
        .filter((name) => typeof Object.getOwnPropertyDescriptor(prototype, name)?.value === 'function')
        .map((name) => vi.spyOn(service as Record<string, () => unknown>, name));
}

describe('FlowVersionPreviewComponent', () => {
    let responses: Map<number, Subject<PreviewGraphVersionResponse>>;
    let fixture: ComponentFixture<FlowVersionPreviewComponent>;

    beforeEach(() => {
        responses = new Map();
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: FlowsApiService,
                    useValue: {
                        previewGraphVersion: (versionId: number) => {
                            const response = new Subject<PreviewGraphVersionResponse>();
                            responses.set(versionId, response);
                            return response;
                        },
                    },
                },
                { provide: SecretsStorageService, useValue: { getSecrets: () => of([]) } },
                { provide: Dialog, useValue: { open: vi.fn(), openDialogs: [] } },
            ],
        });
        // jsdom cannot lay out the Foblex canvas; the handlers under test do not need it.
        TestBed.overrideComponent(FlowGraphComponent, { set: { template: '', imports: [] } });
    });

    afterEach(() => vi.restoreAllMocks());

    async function render(versionId: number): Promise<void> {
        fixture.componentRef.setInput('version', version(versionId));
        fixture.detectChanges();
        // Not whenStable(): a loading resource keeps the app unstable until its response arrives.
        TestBed.tick();
        await Promise.resolve();
    }

    async function respond(versionId: number, pythonNodeName: string, warnings: RestoreWarning[] = []): Promise<void> {
        await respondWith(versionId, snapshotFor(pythonNodeName), warnings);
    }

    async function respondWith(
        versionId: number,
        snapshot: GraphVersionSnapshot,
        warnings: RestoreWarning[] = []
    ): Promise<void> {
        const response = responses.get(versionId)!;
        response.next({ snapshot, warnings });
        response.complete();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function previewFlowService(): FlowService {
        return fixture.debugElement.injector.get(FlowService);
    }

    function flowGraph(): FlowGraphComponent {
        return fixture.debugElement.query(By.directive(FlowGraphComponent)).componentInstance as FlowGraphComponent;
    }

    it('gets its own instance of every flow-editor service', () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        for (const service of EDITOR_SERVICES) {
            expect(fixture.debugElement.injector.get(service)).not.toBe(TestBed.inject(service));
        }
    });

    it('never touches the live (root) editor services', async () => {
        const rootSpies = EDITOR_SERVICES.flatMap((service) => spyOnAllMethods(TestBed.inject(service) as object));
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);

        await render(1);
        await respond(1, 'Preview python');
        const graph = flowGraph();
        const pythonNode = previewFlowService()
            .nodes()
            .find((node) => node.type === NodeType.PYTHON)!;
        expect(pythonNode.node_name).toBe('Preview python');

        // Empty selection: a real copy is handed to the live clipboard on purpose (covered below).
        graph['fFlowComponent'] = {
            getSelection: () => ({ fNodeIds: [], fGroupIds: [], fConnectionIds: [] }),
        } as unknown as FlowGraphComponent['fFlowComponent'];
        graph.onOpenNodePanel(pythonNode);
        graph.onDragStarted({ fData: { fNodeIds: [pythonNode.id] } } as unknown as FDragStartedEvent);
        graph.onCopy();
        graph.onDelete();
        graph.onDeleteNode(pythonNode);
        graph.onUndo();
        fixture.detectChanges();

        expect(fixture.debugElement.injector.get(SidePanelService).selectedNodeId()).toBe(pythonNode.id);
        for (const spy of rootSpies) {
            expect(spy, spy.getMockName()).not.toHaveBeenCalled();
        }
    });

    it('renders only the latest version when the version changes before the first loads', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        const firstResponse = responses.get(1)!;
        await render(2);

        expect(firstResponse.observed).toBe(false);
        await respond(2, 'Second');
        firstResponse.next({ snapshot: snapshotFor('First'), warnings: [] });
        fixture.detectChanges();

        const names = previewFlowService()
            .nodes()
            .map((node) => node.node_name);
        expect(names).toContain('Second');
        expect(names).not.toContain('First');
    });

    it('shows the warning count and emits closed on Exit', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        const closed = vi.fn();
        fixture.componentInstance.closed.subscribe(closed);
        await render(1);
        await respond(1, 'Python', [
            { type: 'fk_nulled', node_id: 2, reason: 'LLM config is missing' },
            { type: 'node_skipped', reason: 'Unsupported node' },
        ]);

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.preview-bar__warnings')?.textContent).toContain('2 warnings');

        (element.querySelector('.preview-bar__exit') as HTMLButtonElement).click();
        expect(closed).toHaveBeenCalledTimes(1);
    });

    it('jumps from a warning to the node in the preview, through the snapshot id', async () => {
        const dialog = TestBed.inject(Dialog) as unknown as { open: ReturnType<typeof vi.fn> };
        dialog.open.mockReturnValue({ closed: of(2) }); // the Python node's id in the snapshot
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respond(1, 'Python', [{ type: 'fk_nulled', node_id: 2, reason: 'LLM config is missing' }]);

        (fixture.nativeElement.querySelector('.preview-bar__warnings') as HTMLButtonElement).click();

        const pythonNode = previewFlowService()
            .nodes()
            .find((node) => node.type === NodeType.PYTHON)!;
        expect(fixture.debugElement.injector.get(SidePanelService).selectedNodeId()).toBe(pythonNode.id);
        expect(TestBed.inject(SidePanelService).selectedNodeId()).toBeNull();
    });

    it('hands nodes copied in the preview to the live clipboard and says so', async () => {
        const info = vi.fn();
        const success = vi.spyOn(TestBed.inject(ToastService), 'success').mockImplementation(info);
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respond(1, 'Copied python');
        const pythonNode = previewFlowService()
            .nodes()
            .find((node) => node.type === NodeType.PYTHON)!;
        const previewClipboard = fixture.debugElement.injector.get(ClipboardService);
        previewClipboard.copy({ fNodeIds: [pythonNode.id], fGroupIds: [], fConnectionIds: [] });

        flowGraph().copied.emit();

        const liveClipboard = TestBed.inject(ClipboardService);
        expect(liveClipboard).not.toBe(previewClipboard);
        expect(liveClipboard.getClipboardData()?.nodes.map((node) => node.node_name)).toEqual(['Copied python']);
        expect(success).toHaveBeenCalledWith('Copied', 2000, 'bottom-right');
    });

    it('keeps Exit available when the version fails to load', async () => {
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        responses.get(1)!.error(new Error('boom'));
        await fixture.whenStable();
        fixture.detectChanges();

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.preview-state--error')).not.toBeNull();
        expect(element.querySelector('.preview-bar__exit')).not.toBeNull();
    });

    it('previews an old snapshot that lacks fields newer exports carry', async () => {
        // Older exports: no graph metadata, edge lists or secret declarations; nodes without metadata
        // or the newer optional fields; python code without libraries.
        const oldSnapshot = {
            nodes: [
                { id: 1, node_type: 'StartNode', node_name: '__start__', variables: {} },
                {
                    id: 2,
                    node_type: 'PythonNode',
                    node_name: 'Old python',
                    input_map: {},
                    python_code: { code: 'def main(): pass', entrypoint: 'main' },
                },
            ],
        } as unknown as GraphVersionSnapshot;
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respondWith(1, oldSnapshot);

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.preview-state--error')).toBeNull();
        expect(
            previewFlowService()
                .nodes()
                .map((node) => node.node_name)
        ).toContain('Old python');
    });

    it('shows the error state, not a crash, when the snapshot cannot be mapped', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        const brokenSnapshot = { nodes: [null], edge_list: [] } as unknown as GraphVersionSnapshot;
        fixture = TestBed.createComponent(FlowVersionPreviewComponent);
        await render(1);
        await respondWith(1, brokenSnapshot);

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.preview-state--error')).not.toBeNull();
        expect(element.querySelector('app-flow-graph')).toBeNull();
        expect(element.querySelector('.preview-bar__exit')).not.toBeNull();
        expect(consoleError).toHaveBeenCalled();
    });
});
