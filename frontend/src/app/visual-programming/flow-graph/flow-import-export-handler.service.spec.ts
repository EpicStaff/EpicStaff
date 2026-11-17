import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { EXPORT_WARNING_DURATION_MS } from '@shared/constants';
import { ExportResult, NodeType } from '@shared/models';
import { NEVER, of, throwError } from 'rxjs';

import { ImportExportService } from '../../core/services/import-export.service';
import { FlowCopyImportFacadeService } from '../../features/flows/services/flow-copy-import-facade.service';
import { ToastService } from '../../services/notifications';
import { CdtExportImportService } from '../components/node-panels/classification-decision-table-node-panel/cdt-export-import.service';
import { NodeModel } from '../core/models/node.model';
import { FlowService } from '../services/flow.service';
import { FlowImportExportService } from './flow-import-export-handler.service';
import { FlowSelectionManagerService } from './flow-selection-manager.service';

const FLOW_ID = 7;

function node(id: string, type: NodeType, backendId: number | null): NodeModel {
    return {
        id,
        backendId,
        type,
        node_name: id,
        data: {},
        position: { x: 0, y: 0 },
        ports: [],
        size: { width: 100, height: 100 },
        input_map: {},
        output_variable_path: null,
    } as unknown as NodeModel;
}

describe('FlowImportExportService — exporting', () => {
    let service: FlowImportExportService;
    let selectedNodeIds: ReturnType<typeof signal<string[]>>;
    let partialExport: ReturnType<typeof vi.fn>;
    let cdtExport: ReturnType<typeof vi.fn>;
    let toastWarning: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
        selectedNodeIds = signal<string[]>([]);
        partialExport = vi.fn().mockReturnValue(NEVER);
        cdtExport = vi.fn().mockReturnValue(NEVER);
        TestBed.configureTestingModule({
            providers: [
                FlowImportExportService,
                { provide: FlowSelectionManagerService, useValue: { selectedNodeIds } },
                { provide: ImportExportService, useValue: { partialExport, cdtExport } },
                { provide: FlowCopyImportFacadeService, useValue: {} },
                { provide: CdtExportImportService, useValue: {} },
            ],
        });
        toastWarning = vi.spyOn(TestBed.inject(ToastService), 'warning').mockImplementation(() => undefined);
        TestBed.inject(FlowService).setFlow({
            nodes: [node('python-1', NodeType.PYTHON, 11), node('table-1', NodeType.CLASSIFICATION_TABLE, 12)],
            connections: [],
        });
        service = TestBed.inject(FlowImportExportService);
    });

    describe('selected nodes as JSON', () => {
        beforeEach(() => selectedNodeIds.set(['python-1']));

        it('warns once and sends nothing while the flow has unsaved changes', () => {
            service.onExportSelectedAsJson(FLOW_ID, true);

            expect(toastWarning).toHaveBeenCalledTimes(1);
            expect(toastWarning.mock.calls[0][0]).toBe('Save the flow before exporting');
            expect(partialExport).not.toHaveBeenCalled();
        });

        it('requests the export of the selected nodes when the flow is saved', () => {
            service.onExportSelectedAsJson(FLOW_ID, false);

            expect(toastWarning).not.toHaveBeenCalled();
            expect(partialExport).toHaveBeenCalledTimes(1);
            expect(partialExport.mock.calls[0][0]).toBe(FLOW_ID);
            expect(partialExport.mock.calls[0][1].python_node_list).toEqual([11]);
        });
    });

    describe('selected nodes as CSV', () => {
        beforeEach(() => selectedNodeIds.set(['table-1', 'python-1']));

        it('warns once, not once per node, and sends nothing while the flow has unsaved changes', () => {
            service.onExportSelectedAsCsv(true);

            expect(toastWarning).toHaveBeenCalledTimes(1);
            expect(toastWarning.mock.calls[0][0]).toBe('Save the flow before exporting');
            expect(cdtExport).not.toHaveBeenCalled();
        });

        it('requests the export of each selected node when the flow is saved', () => {
            service.onExportSelectedAsCsv(false);

            expect(toastWarning).not.toHaveBeenCalled();
            expect(cdtExport.mock.calls.map((call) => call[0])).toEqual([12, 11]);
        });
    });

    describe('all nodes as JSON', () => {
        it('warns once and sends nothing while the flow has unsaved changes', () => {
            service.onExportAllAsJson(FLOW_ID, true);

            expect(toastWarning).toHaveBeenCalledTimes(1);
            expect(toastWarning.mock.calls[0][0]).toBe('Save the flow before exporting');
            expect(partialExport).not.toHaveBeenCalled();
        });

        it('requests the export of the whole flow when the flow is saved', () => {
            service.onExportAllAsJson(FLOW_ID, false);

            expect(toastWarning).not.toHaveBeenCalled();
            expect(partialExport).toHaveBeenCalledTimes(1);
            expect(partialExport.mock.calls[0][1].classification_decision_table_node_list).toEqual([12]);
        });

        it('states why the export failed', () => {
            const toastError = vi.spyOn(TestBed.inject(ToastService), 'error').mockImplementation(() => undefined);
            partialExport.mockReturnValue(
                throwError(() => new HttpErrorResponse({ status: 0, error: new ProgressEvent('error') }))
            );

            service.onExportAllAsJson(FLOW_ID, false);

            expect(toastError.mock.calls.map(([message]) => message)).toEqual([
                "Couldn't export the nodes. The server couldn't be reached.",
            ]);
        });

        it('says there is nothing to export for a flow with only Start and End, saved or not', () => {
            TestBed.inject(FlowService).setFlow({
                nodes: [node('start', NodeType.START, 1), node('end', NodeType.END, 2)],
                connections: [],
            });

            service.onExportAllAsJson(FLOW_ID, false);

            expect(toastWarning).toHaveBeenCalledTimes(1);
            expect(toastWarning.mock.calls[0][0]).toBe('No nodes to export');
            expect(partialExport).not.toHaveBeenCalled();
        });
    });
});

describe('FlowImportExportService — importing', () => {
    it('states why the import failed', () => {
        TestBed.configureTestingModule({
            providers: [
                FlowImportExportService,
                { provide: FlowSelectionManagerService, useValue: { selectedNodeIds: signal<string[]>([]) } },
                { provide: ImportExportService, useValue: {} },
                {
                    provide: FlowCopyImportFacadeService,
                    useValue: {
                        partialImport: () =>
                            throwError(
                                () =>
                                    new HttpErrorResponse({
                                        status: 400,
                                        error: { message: 'The file is not a node export.' },
                                    })
                            ),
                    },
                },
                { provide: CdtExportImportService, useValue: {} },
            ],
        });
        const toastError = vi.spyOn(TestBed.inject(ToastService), 'error').mockImplementation(() => undefined);
        const fileInput = document.createElement('input');
        vi.spyOn(document, 'createElement').mockReturnValue(fileInput);
        vi.spyOn(fileInput, 'click').mockImplementation(() => undefined);
        const onImported = vi.fn();

        TestBed.inject(FlowImportExportService).onImportNodes(FLOW_ID, onImported);
        // The user picks a file in the dialog the click opened.
        Object.defineProperty(fileInput, 'files', { value: [new File(['{}'], 'nodes.json')] });
        fileInput.dispatchEvent(new Event('change'));

        expect(toastError.mock.calls.map(([message]) => message)).toEqual([
            "Couldn't import the nodes. The file is not a node export.",
        ]);
        expect(onImported).not.toHaveBeenCalled();
        vi.restoreAllMocks();
    });
});

const savedAgentNode = { id: 'agent-1', backendId: 7, type: NodeType.AGENT } as NodeModel;

function exportAll(exportResult: ExportResult) {
    const toast = { success: vi.fn(), warning: vi.fn(), error: vi.fn() };

    TestBed.configureTestingModule({
        providers: [
            FlowImportExportService,
            { provide: FlowService, useValue: { nodes: () => [savedAgentNode], connections: () => [] } },
            { provide: FlowSelectionManagerService, useValue: { selectedNodeIds: () => [] } },
            { provide: ImportExportService, useValue: { partialExport: () => of(exportResult) } },
            { provide: CdtExportImportService, useValue: {} },
            { provide: ToastService, useValue: toast },
        ],
    });

    TestBed.inject(FlowImportExportService).onExportAllAsJson(1, false);
    return toast;
}

describe('FlowImportExportService partial export', () => {
    beforeEach(() => {
        vi.stubGlobal('URL', { createObjectURL: () => 'blob:test', revokeObjectURL: () => undefined });
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('warns for the shared duration, bottom-right, about entities the user could not export', () => {
        const toast = exportAll({
            blob: new Blob(['{}']),
            excluded: [{ type: 'AgentDefinition', count: 2, names: ['Alpha', 'Beta'] }],
        });

        expect(toast.success).toHaveBeenCalledTimes(1);
        expect(toast.warning).toHaveBeenCalledTimes(1);
        const [message, duration, position] = toast.warning.mock.calls[0] as [string, number, string];
        expect(message).toContain('Alpha, Beta');
        expect(duration).toBe(EXPORT_WARNING_DURATION_MS);
        expect(position).toBe('bottom-right');
    });

    it('shows no warning when nothing was excluded', () => {
        const toast = exportAll({ blob: new Blob(['{}']), excluded: [] });

        expect(toast.success).toHaveBeenCalledTimes(1);
        expect(toast.warning).not.toHaveBeenCalled();
    });
});
