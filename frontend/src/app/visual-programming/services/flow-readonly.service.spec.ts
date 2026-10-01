import { TestBed } from '@angular/core/testing';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { FlowReadOnlyService } from './flow-readonly.service';

function setUp({ isPreview, canUpdateFlows }: { isPreview: boolean; canUpdateFlows: boolean }) {
    const toast = { info: vi.fn() };
    TestBed.configureTestingModule({
        providers: [
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: PermissionsService, useValue: { can: () => canUpdateFlows } },
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
});
