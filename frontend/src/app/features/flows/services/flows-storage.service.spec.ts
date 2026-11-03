import { TestBed } from '@angular/core/testing';
import { BulkDeleteResponse } from '@shared/models';
import { of } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GetGraphLightRequest } from '../models/graph.model';
import { FlowsApiService } from './flows-api.service';
import { FlowsStorageService } from './flows-storage.service';
import { LabelsStorageService } from './labels-storage.service';

function buildResponse(overrides: Partial<BulkDeleteResponse> = {}): BulkDeleteResponse {
    return {
        dry_run: false,
        deleted_count: 0,
        deleted_ids: [],
        deletable_ids: [],
        not_found_ids: [],
        skipped: [],
        usage: {},
        ...overrides,
    };
}

function flow(id: number, overrides: Partial<GetGraphLightRequest> = {}): GetGraphLightRequest {
    return { id, uuid: `uuid-${id}`, name: `Flow ${id}`, description: '', ...overrides };
}

describe('FlowsStorageService', () => {
    let service: FlowsStorageService;
    let flowsApiService: {
        getGraphsLight: ReturnType<typeof vi.fn>;
        bulkDeleteGraphs: ReturnType<typeof vi.fn>;
    };

    beforeEach(() => {
        flowsApiService = {
            getGraphsLight: vi.fn().mockReturnValue(of([])),
            bulkDeleteGraphs: vi.fn(),
        };

        TestBed.configureTestingModule({
            providers: [
                { provide: FlowsApiService, useValue: flowsApiService as unknown as FlowsApiService },
                {
                    provide: LabelsStorageService,
                    useValue: { labels: vi.fn().mockReturnValue([]) } as unknown as LabelsStorageService,
                },
            ],
        });
        service = TestBed.inject(FlowsStorageService);
    });

    function seedFlows(flows: GetGraphLightRequest[]): void {
        flowsApiService.getGraphsLight.mockReturnValue(of(flows));
        service.getFlows(true).subscribe();
    }

    describe('bulkDelete', () => {
        it('removes deleted_ids and not_found_ids from flows, a parent subflows list, selection and the include filter', () => {
            seedFlows([flow(1), flow(2, { subflows: [{ id: 1, name: 'Flow 1', description: '' }] }), flow(3)]);
            service.selectedFlowIds.set([1, 3]);
            service.patchFilter({ includedFlowIds: [1, 3] });

            flowsApiService.bulkDeleteGraphs.mockReturnValue(
                of(buildResponse({ deleted_ids: [1], not_found_ids: [3] }))
            );

            service.bulkDelete([1, 3]).subscribe();

            expect(flowsApiService.bulkDeleteGraphs).toHaveBeenCalledWith([1, 3]);
            expect(service.flows().map((f) => f.id)).toEqual([2]);
            expect(service.flows().find((f) => f.id === 2)?.subflows).toEqual([]);
            expect(service.selectedFlowIds()).toEqual([]);
            expect(service.getCurrentFilter().includedFlowIds).toBeNull();
        });

        it('leaves the include filter non-null when ids remain after removal', () => {
            seedFlows([flow(1), flow(2), flow(3)]);
            service.patchFilter({ includedFlowIds: [1, 2, 3] });

            flowsApiService.bulkDeleteGraphs.mockReturnValue(of(buildResponse({ deleted_ids: [1] })));

            service.bulkDelete([1]).subscribe();

            expect(service.getCurrentFilter().includedFlowIds).toEqual([2, 3]);
        });
    });

    describe('previewBulkDelete', () => {
        it('forwards to the api bulkDeleteGraphs call with dryRun true', () => {
            flowsApiService.bulkDeleteGraphs.mockReturnValue(of(buildResponse({ dry_run: true })));

            service.previewBulkDelete([1, 2]).subscribe();

            expect(flowsApiService.bulkDeleteGraphs).toHaveBeenCalledWith([1, 2], { dryRun: true });
        });
    });

    describe('removeFromCache', () => {
        it('is a no-op for an empty list', () => {
            seedFlows([flow(1)]);

            service.removeFromCache([]);

            expect(service.flows().map((f) => f.id)).toEqual([1]);
        });
    });
});
