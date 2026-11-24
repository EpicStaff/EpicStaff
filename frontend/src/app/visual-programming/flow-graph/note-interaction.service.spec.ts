import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FFlowComponent } from '@foblex/flow';
import { NodeType } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';
import { NodeModel } from '../core/models/node.model';
import { FlowService } from '../services/flow.service';
import { FlowReadOnlyService } from '../services/flow-readonly.service';
import { NodeFactoryService } from '../services/node-factory.service';
import { UndoRedoService } from '../services/undo-redo.service';
import { FlowArrangeAnimatorService } from './flow-arrange-animator.service';
import { FlowSelectionManagerService } from './flow-selection-manager.service';
import { NoteInteractionService } from './note-interaction.service';

const noteWithRegion = {
    id: 'note-1',
    type: NodeType.NOTE,
    data: { linkedRegion: { x: 0, y: 0, width: 200, height: 100 } },
} as unknown as NodeModel;

describe('NoteInteractionService', () => {
    let isReadOnly: WritableSignal<boolean>;

    function createService(): NoteInteractionService {
        isReadOnly = signal(false);
        TestBed.configureTestingModule({
            providers: [
                NoteInteractionService,
                { provide: FlowReadOnlyService, useValue: { isReadOnly } },
                // The user may edit flows: a version preview must lock the area even so.
                { provide: PermissionsService, useValue: { can: () => true } },
                { provide: FlowService, useValue: { nodes: signal([noteWithRegion]) } },
                { provide: FlowSelectionManagerService, useValue: { selectedNodeIds: signal([noteWithRegion.id]) } },
                { provide: NodeFactoryService, useValue: {} },
                { provide: FlowArrangeAnimatorService, useValue: {} },
                { provide: UndoRedoService, useValue: {} },
            ],
        });
        return TestBed.inject(NoteInteractionService);
    }

    it('lets the area of a selected note be moved and resized in an editable flow', () => {
        const service = createService();

        expect(service.isNoteRegionResizable()).toBe(true);
    });

    it('locks the area of a selected note while the flow is read-only, as in a version preview', () => {
        const service = createService();
        isReadOnly.set(true);

        expect(service.isNoteRegionResizable()).toBe(false);
    });

    it('ignores a drag that starts on the area while the flow is read-only', () => {
        const service = createService();
        isReadOnly.set(true);
        const event = { stopPropagation: vi.fn(), preventDefault: vi.fn() } as unknown as PointerEvent;

        service.onRegionResizeStart(event, 'move', {} as FFlowComponent);

        expect(event.preventDefault).not.toHaveBeenCalled();
        expect(service.regionResizeActive()).toBe(false);
    });
});
