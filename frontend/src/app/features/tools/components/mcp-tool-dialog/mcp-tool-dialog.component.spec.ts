import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActionCode, GetMcpToolRequest, ResourceCode } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { McpToolsService } from '../../services/mcp-tools/mcp-tools.service';
import { McpToolDialogComponent } from './mcp-tool-dialog.component';

const existingTool = {
    id: 5,
    name: 'Search',
    transport: 'https://mcp.example.com/sse',
    tool_name: 'search',
    timeout: 30,
    auth_secret_id: 7,
    init_timeout: 10,
} as GetMcpToolRequest;

function create(canUseSecrets: WritableSignal<boolean>, selectedTool?: GetMcpToolRequest) {
    const mcpToolsService = {
        createMcpTool: vi.fn(() => of(existingTool)),
        updateMcpTool: vi.fn(() => of(existingTool)),
        getMcpTools: vi.fn(() => of([])),
    };
    TestBed.configureTestingModule({
        providers: [
            { provide: DialogRef, useValue: { close: vi.fn(), keydownEvents: new Subject<KeyboardEvent>() } },
            { provide: DIALOG_DATA, useValue: { selectedTool } },
            { provide: McpToolsService, useValue: mcpToolsService },
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            {
                provide: SecretsStorageService,
                useValue: { secrets: signal([]), getSecrets: () => of([]), maskTail: (tail: string) => tail },
            },
            {
                provide: PermissionsService,
                useValue: {
                    can: (resource: ResourceCode, action: ActionCode) =>
                        resource === ResourceCode.Secrets && action === ActionCode.Use ? canUseSecrets() : true,
                },
            },
        ],
    });
    TestBed.overrideComponent(McpToolDialogComponent, { set: { template: '', imports: [] } });
    const fixture = TestBed.createComponent(McpToolDialogComponent);
    fixture.detectChanges();
    return { component: fixture.componentInstance, mcpToolsService };
}

describe('McpToolDialogComponent secrets gating', () => {
    it('keeps the stored auth secret on update when the user lacks secrets Use', () => {
        const { component, mcpToolsService } = create(signal(false), existingTool);
        component.form.controls['auth_secret_id'].setValue(9);

        component.onSave();

        expect(component.canUseSecrets()).toBe(false);
        expect(mcpToolsService.updateMcpTool).toHaveBeenCalledWith(5, expect.objectContaining({ auth_secret_id: 7 }));
    });

    it('sends no auth secret on create when the user lacks secrets Use', () => {
        const { component, mcpToolsService } = create(signal(false));
        component.form.patchValue({
            name: 'Search',
            transport: 'https://mcp.example.com/sse',
            tool_name: 'search',
            auth_secret_id: 9,
        });

        component.onSave();

        expect(mcpToolsService.createMcpTool).toHaveBeenCalledWith(expect.objectContaining({ auth_secret_id: null }));
    });

    it('sends the selected auth secret when the user has secrets Use', () => {
        const { component, mcpToolsService } = create(signal(true), existingTool);
        component.form.controls['auth_secret_id'].setValue(9);

        component.onSave();

        expect(mcpToolsService.updateMcpTool).toHaveBeenCalledWith(5, expect.objectContaining({ auth_secret_id: 9 }));
    });

    it('lets a permitted user clear the auth secret with the "No secret" option', () => {
        const { component, mcpToolsService } = create(signal(true), existingTool);
        const noSecret = component.secretItems()[0];
        component.form.controls['auth_secret_id'].setValue(noSecret.value);

        component.onSave();

        expect(noSecret).toEqual({ name: 'No secret', value: null });
        expect(mcpToolsService.updateMcpTool).toHaveBeenCalledWith(
            5,
            expect.objectContaining({ auth_secret_id: null })
        );
    });

    it('follows the secrets Use permission when it is granted after opening', () => {
        const canUseSecrets = signal(false);
        const { component, mcpToolsService } = create(canUseSecrets, existingTool);
        component.form.controls['auth_secret_id'].setValue(9);
        expect(component.canUseSecrets()).toBe(false);

        canUseSecrets.set(true);
        component.onSave();

        expect(component.canUseSecrets()).toBe(true);
        expect(mcpToolsService.updateMcpTool).toHaveBeenCalledWith(5, expect.objectContaining({ auth_secret_id: 9 }));
    });
});
