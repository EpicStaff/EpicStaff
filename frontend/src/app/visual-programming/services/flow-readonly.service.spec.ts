import { TestBed } from '@angular/core/testing';
import { ActionCode, NodeType } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { FlowReadOnlyService, TRIGGER_NODES_NEED_RUN_MESSAGE } from './flow-readonly.service';

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
                        action === ActionCode.Run ? canRunFlows : canUpdateFlows,
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
        it('lets a user who may update and run flows change trigger nodes', () => {
            const { service } = setUp({ isPreview: false, canUpdateFlows: true, canRunFlows: true });

            expect(service.canEditTriggerNodes()).toBe(true);
            expect(service.isNodeTypeReadOnly(NodeType.WEBHOOK_TRIGGER)).toBe(false);
        });

        it('keeps Webhook, Telegram and Schedule triggers read-only without Flows:Run, other nodes editable', () => {
            const { service } = setUp({ isPreview: false, canUpdateFlows: true, canRunFlows: false });

            expect(service.isReadOnly()).toBe(false);
            expect(service.canEditTriggerNodes()).toBe(false);
            expect(service.isNodeTypeReadOnly(NodeType.WEBHOOK_TRIGGER)).toBe(true);
            expect(service.isNodeTypeReadOnly(NodeType.TELEGRAM_TRIGGER)).toBe(true);
            expect(service.isNodeTypeReadOnly(NodeType.SCHEDULE_TRIGGER)).toBe(true);
            expect(service.isNodeTypeReadOnly(NodeType.PYTHON)).toBe(false);
            expect(service.isNodeTypeReadOnly(NodeType.START)).toBe(false);
        });

        it('keeps trigger nodes read-only in a version preview even with Flows:Run', () => {
            const { service } = setUp({ isPreview: true, canUpdateFlows: true, canRunFlows: true });

            expect(service.canEditTriggerNodes()).toBe(false);
            expect(service.isNodeTypeReadOnly(NodeType.SCHEDULE_TRIGGER)).toBe(true);
        });

        it('explains a blocked trigger node with the Run message (throttled), and nothing for an editable node', () => {
            const { service, toast } = setUp({ isPreview: false, canUpdateFlows: true, canRunFlows: false });

            service.notifyNodeTypeBlocked(NodeType.PYTHON);
            service.notifyNodeTypeBlocked(NodeType.WEBHOOK_TRIGGER);
            service.notifyNodeTypeBlocked(NodeType.TELEGRAM_TRIGGER);

            expect(toast.info).toHaveBeenCalledTimes(1);
            expect(toast.info).toHaveBeenCalledWith(TRIGGER_NODES_NEED_RUN_MESSAGE);
        });

        it('explains a blocked node in a read-only editor with the read-only message', () => {
            const { service, toast } = setUp({ isPreview: false, canUpdateFlows: false, canRunFlows: true });

            service.notifyNodeTypeBlocked(NodeType.WEBHOOK_TRIGGER);

            expect(toast.info).toHaveBeenCalledWith('You have read-only access to this flow.');
        });
    });
});
