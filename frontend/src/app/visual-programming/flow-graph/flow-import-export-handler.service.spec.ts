import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { ExportTransferJob } from '../../core/models/transfer-job.model';
import { FlowCopyImportFacadeService } from '../../features/flows/services/flow-copy-import-facade.service';
import { ConfigService } from '../../services/config';
import { ToastService } from '../../services/notifications';
import { NodeModel } from '../core/models/node.model';
import { FlowService } from '../services/flow.service';
import { FlowImportExportService } from './flow-import-export-handler.service';
import { FlowSelectionManagerService } from './flow-selection-manager.service';

const FLOW_ID = 7;
const PARTIAL_EXPORT_JOBS_URL = `/api/graphs/${FLOW_ID}/partial-export-jobs/`;
const CDT_EXPORT_JOBS_URL = '/api/classification-decision-table-node/export-jobs/';
const JOB_URL = '/api/transfer-jobs/job-1/';

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

function finishedJob(overrides: Partial<ExportTransferJob>): ExportTransferJob {
    return {
        id: 'job-1',
        kind: 'export',
        main_entity: 'FlowNodes',
        status: 'completed',
        display_name: 'Nodes',
        file_name: 'nodes.zip',
        result: { excluded: [] },
        error: null,
        created_at: '2026-11-09T10:00:00Z',
        finished_at: '2026-11-09T10:01:00Z',
        expires_at: null,
        ...overrides,
    };
}

describe('FlowImportExportService', () => {
    let service: FlowImportExportService;
    let httpMock: HttpTestingController;
    let selectedNodeIds: ReturnType<typeof signal<string[]>>;
    let toast: {
        show: () => number;
        remove: () => void;
        success: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
        error: ReturnType<typeof vi.fn>;
    };

    beforeEach(() => {
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
        selectedNodeIds = signal<string[]>([]);
        toast = { show: () => 1, remove: () => undefined, success: vi.fn(), warning: vi.fn(), error: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                FlowImportExportService,
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: ToastService, useValue: toast },
                { provide: FlowSelectionManagerService, useValue: { selectedNodeIds } },
                { provide: FlowCopyImportFacadeService, useValue: {} },
            ],
        });
        TestBed.inject(FlowService).setFlow({
            nodes: [
                node('start', NodeType.START, 1),
                node('python-1', NodeType.PYTHON, 11),
                node('table-1', NodeType.CLASSIFICATION_TABLE, 12),
                node('table-2', NodeType.CLASSIFICATION_TABLE, 13),
            ],
            connections: [],
        });
        service = TestBed.inject(FlowImportExportService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        vi.restoreAllMocks();
    });

    /** Accepts the started job, reports it finished as `job`, and hands out its download link. */
    async function finishJob(startUrl: string, job: ExportTransferJob): Promise<void> {
        httpMock.expectOne(startUrl).flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush(job);
        if (job.status === 'completed') {
            httpMock
                .expectOne('/api/transfer-jobs/job-1/download-ticket/')
                .flush({ download_url: '/api/transfer-jobs/job-1/download/?ticket=t-1' });
        }
    }

    function saveFirstWarnings(): unknown[] {
        return toast.warning.mock.calls.filter(([message]) => message === 'Save the flow before exporting');
    }

    describe.each([
        ['selected nodes as JSON', () => service.onExportSelectedAsJson(FLOW_ID, true)],
        ['selected nodes as CSV', () => service.onExportSelectedAsCsv(true)],
        ['all nodes as JSON', () => service.onExportAllAsJson(FLOW_ID, true)],
    ])('%s while the flow has unsaved changes', (_label, exportIt) => {
        it('warns once and starts no export', () => {
            selectedNodeIds.set(['table-1', 'table-2']);

            exportIt();

            expect(saveFirstWarnings()).toHaveLength(1);
            httpMock.expectNone(() => true);
        });
    });

    it('exports the selected nodes as a job of the flow', () => {
        selectedNodeIds.set(['python-1']);

        service.onExportSelectedAsJson(FLOW_ID, false);

        const body = httpMock.expectOne(PARTIAL_EXPORT_JOBS_URL).request.body as Record<string, number[]>;
        expect(body['python_node_list']).toEqual([11]);
        expect(body['classification_decision_table_node_list']).toEqual([]);
    });

    it('exports every node but Start and End when exporting the whole flow', () => {
        service.onExportAllAsJson(FLOW_ID, false);

        const body = httpMock.expectOne(PARTIAL_EXPORT_JOBS_URL).request.body as Record<string, number[]>;
        expect(body['python_node_list']).toEqual([11]);
        expect(body['classification_decision_table_node_list']).toEqual([12, 13]);
    });

    it('says there is nothing to export for a flow with only Start and End', () => {
        TestBed.inject(FlowService).setFlow({
            nodes: [node('start', NodeType.START, 1), node('end', NodeType.END, 2)],
            connections: [],
        });

        service.onExportAllAsJson(FLOW_ID, false);

        expect(toast.warning.mock.calls.map(([message]) => message)).toEqual(['No nodes to export']);
    });

    it('exports each selected decision table to the server CSV in a job of its own', () => {
        selectedNodeIds.set(['table-2', 'python-1', 'table-1']);

        service.onExportSelectedAsCsv(false);

        expect(httpMock.match(CDT_EXPORT_JOBS_URL).map((request) => request.request.body)).toEqual([
            { ids: [12], export_format: 'csv' },
            { ids: [13], export_format: 'csv' },
        ]);
    });

    it('reports the exported nodes once the job finished, and warns about what it left out', async () => {
        service.onExportAllAsJson(FLOW_ID, false);

        await finishJob(
            PARTIAL_EXPORT_JOBS_URL,
            finishedJob({
                result: {
                    excluded: [
                        { entity_type: 'AgentDefinition', entity_id: 4, name: 'Alpha' },
                        { entity_type: 'AgentDefinition', entity_id: 5, name: 'Beta' },
                    ],
                },
            })
        );

        expect(toast.success.mock.calls.map(([message]) => message)).toEqual([
            '3 nodes exported as a .zip archive (Start and End nodes excluded)',
        ]);
        expect(toast.warning).toHaveBeenCalledTimes(1);
        expect(toast.warning.mock.calls[0][0]).toContain('Alpha, Beta');
    });

    it('does not warn when the job left nothing out', async () => {
        selectedNodeIds.set(['python-1']);
        service.onExportSelectedAsJson(FLOW_ID, false);

        await finishJob(PARTIAL_EXPORT_JOBS_URL, finishedJob({}));

        expect(toast.success.mock.calls.map(([message]) => message)).toEqual(['1 node exported as a .zip archive']);
        expect(toast.warning).not.toHaveBeenCalled();
    });

    it('shows the reason a failed job gave, and reports nothing exported', async () => {
        service.onExportAllAsJson(FLOW_ID, false);

        await finishJob(
            PARTIAL_EXPORT_JOBS_URL,
            finishedJob({ status: 'failed', result: null, error: { code: 'not_found', message: 'Nodes not found.' } })
        );

        expect(toast.error.mock.calls.map(([message]) => message)).toEqual(['Nodes not found.']);
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('lets the node import pick a zip export or a plain JSON file', () => {
        const pickedAccepts: string[] = [];
        vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(function (this: HTMLInputElement) {
            pickedAccepts.push(this.accept);
        });

        service.onImportNodes(FLOW_ID, () => true);

        expect(pickedAccepts).toEqual(['.json,.zip']);
    });
});
