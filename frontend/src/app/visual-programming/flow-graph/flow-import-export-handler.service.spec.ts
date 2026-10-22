import { TestBed } from '@angular/core/testing';
import { EXPORT_WARNING_DURATION_MS } from '@shared/constants';
import { ExportResult, NodeType } from '@shared/models';
import { of } from 'rxjs';

import { ImportExportService } from '../../core/services/import-export.service';
import { ToastService } from '../../services/notifications';
import { CdtExportImportService } from '../components/node-panels/classification-decision-table-node-panel/cdt-export-import.service';
import { NodeModel } from '../core/models/node.model';
import { FlowService } from '../services/flow.service';
import { FlowImportExportService } from './flow-import-export-handler.service';
import { FlowSelectionManagerService } from './flow-selection-manager.service';

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

    TestBed.inject(FlowImportExportService).onExportAllAsJson(1);
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
