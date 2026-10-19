import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';
import { Observable, of, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { GraphDto } from '../../../flows/models/graph.model';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import { ChatContractMissing } from '../../models/chat.model';
import { ChatContractFixComponent } from './chat-contract-fix.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const NOTHING_MISSING: ChatContractMissing = {
    missing_start_node: false,
    missing_end_node: false,
    start_variables: [],
    end_outputs: [],
};

/** The flows API over one stored graph: bulk save applies node updates and refuses a stale save_version with 409. */
class FakeFlowsApi {
    graph = {} as GraphDto;
    failNextSave: HttpErrorResponse | null = null;
    // Another editor saving between Apply's fetch and its save.
    editBeforeNextSave = false;

    getGraphById(): Observable<GraphDto> {
        return of(structuredClone(this.graph));
    }

    bulkSaveGraph(_graphId: number, payload: Record<string, unknown>): Observable<GraphDto> {
        if (this.editBeforeNextSave) {
            this.editBeforeNextSave = false;
            this.graph.save_version += 1;
        }
        if (this.failNextSave) return throwError(() => this.failNextSave);
        if (payload['save_version'] !== this.graph.save_version) {
            return throwError(() => new HttpErrorResponse({ status: 409 }));
        }
        for (const key of ['start_node_list', 'end_node_list'] as const) {
            for (const update of (payload[key] ?? []) as Record<string, unknown>[]) {
                const index = this.graph[key].findIndex((node) => node.id === update['id']);
                this.graph[key][index] = { ...this.graph[key][index], ...update };
            }
        }
        this.graph.save_version += 1;
        return of(structuredClone(this.graph));
    }
}

const CHAT_DOMAIN_VARIABLES = {
    chat_history: [],
    user_message: '',
    action: null,
    chat_extra_data: {},
    chat_user_id: null,
    reply: '',
    actions: [],
    request_human: false,
};
const CHAT_OUTPUT_MAP = {
    reply: 'variables.reply',
    actions: 'variables.actions',
    request_human: 'variables.request_human',
};

describe('ChatContractFixComponent', () => {
    let fixture: ComponentFixture<ChatContractFixComponent>;
    let flowsApi: FakeFlowsApi;
    let grantedFlowActions: ActionCode[];
    let appliedCount: number;
    const toast = { success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() };

    async function render(missing: ChatContractMissing): Promise<void> {
        fixture = TestBed.createComponent(ChatContractFixComponent);
        fixture.componentRef.setInput('graphId', 7);
        fixture.componentRef.setInput('missing', missing);
        fixture.componentInstance.applied.subscribe(() => appliedCount++);
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function text(): string {
        return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ').trim() ?? '';
    }

    function applyButton(): HTMLButtonElement | null {
        const buttons = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button'));
        return buttons.find((button) => /Apply to flow|Applying/.test(button.textContent ?? '')) ?? null;
    }

    async function clickApply(): Promise<void> {
        applyButton()!.click();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.clearAllMocks();
        appliedCount = 0;
        grantedFlowActions = [ActionCode.Read, ActionCode.Update];
        flowsApi = new FakeFlowsApi();
        flowsApi.graph = {
            id: 7,
            save_version: 4,
            start_node_list: [
                {
                    id: 11,
                    graph: 7,
                    variables: {
                        variables: { context: 'ctx', user_message: 'hi' },
                        persistent_variables: { user: ['context'], organization: [] },
                    },
                    metadata: { position: { x: 0, y: 0 } },
                },
            ],
            end_node_list: [
                {
                    id: 12,
                    graph: 7,
                    output_map: { context: 'variables.context' },
                    metadata: { position: { x: 5, y: 0 } },
                },
            ],
        } as unknown as GraphDto;
        TestBed.configureTestingModule({
            imports: [ChatContractFixComponent],
            providers: [
                provideRouter([]),
                { provide: FlowsApiService, useValue: flowsApi },
                { provide: ToastService, useValue: toast },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Flows && grantedFlowActions.includes(action),
                    },
                },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('adds the missing chat variables and outputs to the flow and keeps what it has', async () => {
        await render({ ...NOTHING_MISSING, start_variables: ['chat_history'], end_outputs: ['reply'] });
        expect(text()).toContain('Start node Domain variables: chat_history, user_message');
        expect(text()).toContain('End node outputs: reply, actions, request_human');

        await clickApply();

        expect(flowsApi.graph.start_node_list[0].variables).toEqual({
            variables: { ...CHAT_DOMAIN_VARIABLES, context: 'ctx', user_message: 'hi' },
            persistent_variables: { user: ['context'], organization: [] },
        });
        expect(flowsApi.graph.end_node_list[0].output_map).toEqual({
            ...CHAT_OUTPUT_MAP,
            context: 'variables.context',
        });
        expect(toast.success).toHaveBeenCalled();
        expect(appliedCount).toBe(1);
    });

    it('saves nothing and says so when the flow was fixed since the check', async () => {
        flowsApi.graph.start_node_list[0].variables = { variables: CHAT_DOMAIN_VARIABLES };
        flowsApi.graph.end_node_list[0].output_map = CHAT_OUTPUT_MAP;
        await render({ ...NOTHING_MISSING, end_outputs: ['reply'] });

        await clickApply();

        expect(flowsApi.graph.save_version).toBe(4);
        expect(toast.info).toHaveBeenCalledWith('The flow already meets the chat contract');
        expect(toast.success).not.toHaveBeenCalled();
        expect(appliedCount).toBe(1);
    });

    it('keeps the panel and says so when the flow changed meanwhile', async () => {
        await render({ ...NOTHING_MISSING, start_variables: ['chat_history'] });
        flowsApi.editBeforeNextSave = true;

        await clickApply();

        expect(toast.warning).toHaveBeenCalledWith('The flow changed meanwhile. Apply the fix again.');
        expect(appliedCount).toBe(0);
        expect(applyButton()!.disabled).toBe(false);
        expect(flowsApi.graph.start_node_list[0].variables['variables']).not.toHaveProperty('chat_history');
    });

    it('says why another failure did not apply, and lets the user try again', async () => {
        await render({ ...NOTHING_MISSING, start_variables: ['chat_history'] });
        flowsApi.failNextSave = new HttpErrorResponse({ status: 500, error: { detail: 'Database down' } });

        await clickApply();

        expect(toast.error).toHaveBeenCalled();
        expect(appliedCount).toBe(0);
        expect(applyButton()!.disabled).toBe(false);
    });

    it('has no Apply without the right to edit flows, and says who can apply it', async () => {
        grantedFlowActions = [ActionCode.Read];
        await render({ ...NOTHING_MISSING, start_variables: ['chat_history'], end_outputs: ['reply'] });

        expect(applyButton()).toBeNull();
        expect(text()).toContain('Someone who can edit this flow must apply these changes.');
    });

    it('links to the flow editor instead of fixing a flow without an end node', async () => {
        await render({ ...NOTHING_MISSING, missing_end_node: true, start_variables: ['chat_history'] });

        expect(applyButton()).toBeNull();
        const link = (fixture.nativeElement as HTMLElement).querySelector('a');
        expect(link?.textContent?.trim()).toBe('Open flow');
        expect(link?.getAttribute('href')).toBe('/flows/7');
    });
});
