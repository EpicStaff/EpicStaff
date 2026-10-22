import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';
import { NEVER } from 'rxjs';

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
        color: '',
        icon: '',
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
