import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActionCode, NodeType, ResourceCode } from '@shared/models';
import type { Mock } from 'vitest';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import {
    FLOW_ACTIONS_USE_WITHOUT_UPDATE,
    FLOW_ACTIONS_WITH_USE,
    FLOW_ACTIONS_WITHOUT_USE,
    grantPermissions,
} from '../utils/testing/permissions.fixture';
import {
    FILE_NODES_NEED_FILES_READ_MESSAGE,
    FlowReadOnlyService,
    TRIGGER_NODES_NEED_USE_MESSAGE,
} from './flow-readonly.service';

function setUp({
    isPreview,
    canUpdateFlows,
    canRunFlows = true,
}: {
    isPreview: boolean;
    canUpdateFlows: boolean;
    canRunFlows?: boolean;
}) {
    const toast = { info: vi.fn() };
    TestBed.configureTestingModule({
        providers: [
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            {
                provide: PermissionsService,
                useValue: {
                    can: (_resource: unknown, action: ActionCode) =>
                        action === ActionCode.Use ? canRunFlows : canUpdateFlows,
                },
            },
            { provide: ToastService, useValue: toast },
        ],
    });
    return { service: TestBed.inject(FlowReadOnlyService), toast };
}

describe('FlowReadOnlyService', () => {
    it('is editable for a user who may update flows, outside a preview', () => {
        expect(setUp({ isPreview: false, canUpdateFlows: true }).service.isReadOnly()).toBe(false);
    });

    it('is read-only for a user without Flows:Update, with a throttled message', () => {
        const { service, toast } = setUp({ isPreview: false, canUpdateFlows: false });

        service.notifyBlocked();
        service.notifyBlocked();

        expect(service.isReadOnly()).toBe(true);
        expect(toast.info).toHaveBeenCalledTimes(1);
        expect(toast.info).toHaveBeenCalledWith('You have read-only access to this flow.');
    });

    it('is read-only in a version preview whatever the permissions, with the preview message', () => {
        const { service, toast } = setUp({ isPreview: true, canUpdateFlows: true });

        service.notifyBlocked();
        service.notifyBlocked();

        expect(service.isReadOnly()).toBe(true);
        expect(toast.info).toHaveBeenCalledTimes(1);
        expect(toast.info).toHaveBeenCalledWith(
            'Preview mode is read-only. Exit preview to edit the flow',
            3000,
            'bottom-right'
        );
    });

    describe('trigger nodes', () => {
        const TRIGGER_NODE_TYPES = [NodeType.WEBHOOK_TRIGGER, NodeType.TELEGRAM_TRIGGER, NodeType.SCHEDULE_TRIGGER];
        const OTHER_NODE_TYPES = [NodeType.START, NodeType.PYTHON, NodeType.NOTE, NodeType.END];

        /** The real PermissionsService, holding exactly these Flows actions. */
        function serviceFor(isPreview: boolean, flowActions: ActionCode[]): FlowReadOnlyService {
            TestBed.configureTestingModule({
                providers: [provideHttpClient(), { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview }],
            });
            grantPermissions({ [ResourceCode.Flows]: flowActions });
            return TestBed.inject(FlowReadOnlyService);
        }

        describe.each([
            {
                user: 'may update and run flows',
                isPreview: false,
                flowActions: FLOW_ACTIONS_WITH_USE,
                triggerReadOnly: false,
                otherReadOnly: false,
            },
            {
                user: 'may update but not run flows',
                isPreview: false,
                flowActions: FLOW_ACTIONS_WITHOUT_USE,
                triggerReadOnly: true,
                otherReadOnly: false,
            },
            {
                user: 'may run but not update flows',
                isPreview: false,
                flowActions: FLOW_ACTIONS_USE_WITHOUT_UPDATE,
                triggerReadOnly: true,
                otherReadOnly: true,
            },
            {
                user: 'may update and run flows, in a version preview',
                isPreview: true,
                flowActions: FLOW_ACTIONS_WITH_USE,
                triggerReadOnly: true,
                otherReadOnly: true,
            },
        ])('for a user who $user', ({ isPreview, flowActions, triggerReadOnly, otherReadOnly }) => {
            it.each(TRIGGER_NODE_TYPES)(`a %s node is read-only: ${triggerReadOnly}`, (type) => {
                const service = serviceFor(isPreview, flowActions);

                expect(service.isNodeTypeReadOnly(type)).toBe(triggerReadOnly);
                expect(service.canEditTriggerNodes()).toBe(!triggerReadOnly);
            });

            it.each(OTHER_NODE_TYPES)(`a %s node is read-only: ${otherReadOnly}`, (type) => {
                expect(serviceFor(isPreview, flowActions).isNodeTypeReadOnly(type)).toBe(otherReadOnly);
            });
        });

        it('explains a blocked trigger node with the Use message (throttled), and nothing for an editable node', () => {
            const { service, toast } = setUp({ isPreview: false, canUpdateFlows: true, canRunFlows: false });

            service.notifyNodeTypeBlocked(NodeType.PYTHON);
            service.notifyNodeTypeBlocked(NodeType.WEBHOOK_TRIGGER);
            service.notifyNodeTypeBlocked(NodeType.TELEGRAM_TRIGGER);

            expect(toast.info).toHaveBeenCalledTimes(1);
            expect(toast.info).toHaveBeenCalledWith(TRIGGER_NODES_NEED_USE_MESSAGE);
        });

        it('explains a blocked node in a read-only editor with the read-only message', () => {
            const { service, toast } = setUp({ isPreview: false, canUpdateFlows: false, canRunFlows: true });

            service.notifyNodeTypeBlocked(NodeType.WEBHOOK_TRIGGER);

            expect(toast.info).toHaveBeenCalledWith('You have read-only access to this flow.');
        });
    });

    describe('nodes that always read the flow files', () => {
        const FILE_NODE_TYPES = [NodeType.FILE_EXTRACTOR, NodeType.AUDIO_TO_TEXT];

        /** The real PermissionsService, holding Flows:Update and exactly these Files actions. */
        function serviceWithFiles(filesActions: ActionCode[]): { service: FlowReadOnlyService; toast: { info: Mock } } {
            const toast = { info: vi.fn() };
            TestBed.configureTestingModule({
                providers: [
                    provideHttpClient(),
                    { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                    { provide: ToastService, useValue: toast },
                ],
            });
            grantPermissions({ [ResourceCode.Flows]: FLOW_ACTIONS_WITH_USE, [ResourceCode.Files]: filesActions });
            return { service: TestBed.inject(FlowReadOnlyService), toast };
        }

        it.each(FILE_NODE_TYPES)('a %s node is read-only without Files:Read', (type) => {
            expect(serviceWithFiles([ActionCode.Create]).service.isNodeTypeReadOnly(type)).toBe(true);
        });

        it.each(FILE_NODE_TYPES)('a %s node stays editable with Files:Read', (type) => {
            expect(serviceWithFiles([ActionCode.Read]).service.isNodeTypeReadOnly(type)).toBe(false);
        });

        it.each([NodeType.PYTHON, NodeType.START, NodeType.NOTE, NodeType.END])(
            'a %s node does not need Files:Read',
            (type) => {
                expect(serviceWithFiles([]).service.isNodeTypeReadOnly(type)).toBe(false);
            }
        );

        it('explains a blocked file node with the Files:Read message, throttled, and not with the Use message', () => {
            const { service, toast } = serviceWithFiles([]);

            service.notifyNodeTypeBlocked(NodeType.FILE_EXTRACTOR);
            service.notifyNodeTypeBlocked(NodeType.AUDIO_TO_TEXT);

            expect(FILE_NODES_NEED_FILES_READ_MESSAGE).toBe('You need Files: Read to use this node.');
            expect(toast.info).toHaveBeenCalledTimes(1);
            expect(toast.info).toHaveBeenCalledWith(FILE_NODES_NEED_FILES_READ_MESSAGE);
        });
    });

    describe('Python code that reads secrets', () => {
        it.each([
            { secretActions: [ActionCode.Use], secretIds: [7], locked: false },
            { secretActions: [ActionCode.Read], secretIds: [7], locked: true },
            { secretActions: [], secretIds: [7, 8], locked: true },
            { secretActions: [], secretIds: [], locked: false },
        ])(
            'is locked for Secrets actions $secretActions and secret ids $secretIds: $locked',
            ({ secretActions, secretIds, locked }) => {
                TestBed.configureTestingModule({
                    providers: [provideHttpClient(), { provide: FLOW_EDITOR_PREVIEW, useValue: false }],
                });
                grantPermissions({
                    [ResourceCode.Flows]: FLOW_ACTIONS_WITH_USE,
                    [ResourceCode.Secrets]: secretActions,
                });

                expect(TestBed.inject(FlowReadOnlyService).isSecretCodeLocked(secretIds)).toBe(locked);
            }
        );
    });
});
