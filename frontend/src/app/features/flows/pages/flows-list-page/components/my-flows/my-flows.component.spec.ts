import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';

import { FlowRenameDialogComponent } from '../../../../components/flow-rename-dialog/flow-rename-dialog.component';
import { FlowsStorageService } from '../../../../services/flows-storage.service';

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { AuthorshipDetailsDialogService, ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode, UserSummary } from '@shared/models';
import { Observable, of, throwError } from 'rxjs';

import { ImportExportService } from '../../../../../../core/services/import-export.service';
import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../services/notifications';
import { GetGraphLightRequest } from '../../../../models/graph.model';
import { FlowsApiService } from '../../../../services/flows-api.service';
import { LabelsStorageService } from '../../../../services/labels-storage.service';
import { RunGraphService } from '../../../../services/run-graph-session.service';
import { MyFlowsComponent } from './my-flows.component';

const SOURCE_FLOW: GetGraphLightRequest = { id: 7, uuid: 'uuid-7', name: 'Support Flow', description: '' };

describe('MyFlowsComponent copy action', () => {
    const copyFlow = vi.fn();
    const toastSuccess = vi.fn();

    beforeEach(() => {
        copyFlow.mockReset().mockReturnValue(of({ name: 'Support Flow #2' }));
        toastSuccess.mockReset();

        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                {
                    provide: FlowsStorageService,
                    useValue: {
                        filteredFlows: signal([]),
                        // Keeps the template on the spinner so no flow cards render.
                        isFlowsLoaded: signal(false),
                        selectMode: signal(false),
                        selectedFlowIds: signal([]),
                        getFlows: () => of([]),
                        copyFlow,
                    },
                },
                { provide: LabelsStorageService, useValue: { activeLabelFilter: signal('all') } },
                { provide: FlowsApiService, useValue: {} },
                { provide: RunGraphService, useValue: {} },
                { provide: ToastService, useValue: { success: toastSuccess, error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: ImportExportService, useValue: {} },
            ],
        });
    });

    function openCopyDialog(closedWith: string | undefined): ReturnType<typeof vi.spyOn> {
        const fixture = TestBed.createComponent(MyFlowsComponent);
        fixture.detectChanges();
        // Spy on the Dialog instance the component actually injected (DialogModule provides its own).
        const dialog = fixture.debugElement.injector.get(Dialog);
        const openSpy = vi
            .spyOn(dialog, 'open')
            .mockReturnValue({ closed: of(closedWith) } as unknown as DialogRef<unknown, unknown>);

        fixture.componentInstance.handleFlowCardAction({ action: 'copy', flow: SOURCE_FLOW });
        return openSpy;
    }

    it('pre-fills the dialog with the plain source name, leaving numbering to the backend', () => {
        const openSpy = openCopyDialog(undefined);

        expect(openSpy).toHaveBeenCalledWith(
            FlowRenameDialogComponent,
            expect.objectContaining({ data: { flowName: 'Support Flow', title: 'Copy Flow' } })
        );
        expect(copyFlow).not.toHaveBeenCalled();
    });

    it('sends the name as entered, trimmed, without adding a number', () => {
        openCopyDialog('  Support Flow  ');

        expect(copyFlow).toHaveBeenCalledWith(7, 'Support Flow');
        expect(toastSuccess).toHaveBeenCalledWith('Flow copied and saved as "Support Flow #2"');
    });
});


const OWNER: UserSummary = { id: 1, display_name: 'Ivan Bohun', avatar_url: null };
const EDITOR: UserSummary = { id: 2, display_name: 'Olena Petrenko', avatar_url: null };

// As listed by graph-light: the subflow rows of a card carry no authorship.
const FLOW: GetGraphLightRequest = {
    id: 337,
    uuid: 'flow-337',
    name: 'Test Flow 1',
    description: '',
    created_by: OWNER,
    created_at: '2026-03-12T13:28:23Z',
    last_edited_by: EDITOR,
    last_edited_at: '2026-09-02T12:40:19Z',
    updated_at: '2026-09-02T12:40:19Z',
    subflows: [{ id: 366, name: 'Subflow 1', description: '', updated_at: '2026-09-01T10:00:00Z' }],
};

// The same subflow as its own entry in the list, with its authorship.
const SUBFLOW: GetGraphLightRequest = {
    id: 366,
    uuid: 'flow-366',
    name: 'Subflow 1',
    description: '',
    created_by: EDITOR,
    created_at: '2026-04-01T08:00:00Z',
    last_edited_by: null,
    last_edited_at: null,
    updated_at: '2026-09-01T10:00:00Z',
};

// The light model leaves authorship optional; a flow that lacks it.
const FLOW_WITHOUT_AUTHORSHIP: GetGraphLightRequest = { id: 400, uuid: 'flow-400', name: 'Legacy', description: '' };

interface Setup {
    flows: GetGraphLightRequest[];
    canWrite?: boolean;
    // What graph-light/<id>/ returns for a flow that is not in the loaded list.
    fetchedFlow?: Observable<GetGraphLightRequest>;
}

interface Rendered {
    fixture: ComponentFixture<MyFlowsComponent>;
    host: HTMLElement;
    open: ReturnType<typeof vi.fn>;
    getGraphLightById: ReturnType<typeof vi.fn>;
    getGraphById: ReturnType<typeof vi.fn>;
    toastError: ReturnType<typeof vi.fn>;
}

// jsdom has no ResizeObserver; the "Last modified" strip measures itself with one.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

function render({ flows, canWrite = true, fetchedFlow }: Setup): Rendered {
    const open = vi.fn();
    const getGraphLightById = vi.fn(() => fetchedFlow ?? throwError(() => new Error('not stubbed')));
    // The full graph (every node) is never needed for the details dialog.
    const getGraphById = vi.fn(() => throwError(() => new Error('the full graph must not be fetched')));
    const toastError = vi.fn();
    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            {
                provide: FlowsApiService,
                useValue: { getGraphsLight: () => of(flows), getGraphLightById, getGraphById },
            },
            { provide: LabelsStorageService, useValue: { labels: signal([]), activeLabelFilter: signal('all') } },
            { provide: AuthorshipDetailsDialogService, useValue: { open } },
            {
                provide: PermissionsService,
                useValue: {
                    can: (_resource: ResourceCode, action: ActionCode) => canWrite || action === ActionCode.Read,
                },
            },
            { provide: ToastService, useValue: { error: toastError, success: vi.fn() } },
            { provide: RunGraphService, useValue: {} },
            { provide: ConfirmationDialogService, useValue: {} },
            { provide: ImportExportService, useValue: {} },
        ],
    });
    const fixture = TestBed.createComponent(MyFlowsComponent);
    // The first pass loads the flows, the second renders their cards.
    fixture.detectChanges();
    fixture.detectChanges();
    return { fixture, host: fixture.nativeElement as HTMLElement, open, getGraphLightById, getGraphById, toastError };
}

function card(host: HTMLElement, flowName: string): HTMLElement {
    return Array.from(host.querySelectorAll<HTMLElement>('.flow-card')).find(
        (flowCard) => flowCard.querySelector('.flow-name')?.textContent?.trim() === flowName
    )!;
}

function cardMenuButton(flowCard: HTMLElement): HTMLButtonElement {
    return flowCard.querySelector<HTMLButtonElement>('.card-main .menu-button')!;
}

function subflowMenuButton(flowCard: HTMLElement): HTMLButtonElement {
    return flowCard.querySelector<HTMLButtonElement>('.subflow-item .menu-button')!;
}

function expandSubflows(fixture: ComponentFixture<MyFlowsComponent>, flowCard: HTMLElement): void {
    flowCard.querySelector<HTMLElement>('.card-actions app-button')!.click();
    fixture.detectChanges();
}

function chooseViewDetails(fixture: ComponentFixture<MyFlowsComponent>, menuButton: HTMLButtonElement): void {
    menuButton.click();
    fixture.detectChanges();
    const item = Array.from(
        fixture.nativeElement.querySelectorAll('.context-menu .menu-item') as NodeListOf<HTMLElement>
    ).find((menuItem) => menuItem.textContent?.trim() === 'View Details')!;
    item.click();
    fixture.detectChanges();
}

describe('MyFlowsComponent "View Details"', () => {
    it("opens Flow Details with the flow's owner and last editor, closing back to the card's ⋮ button", () => {
        const { fixture, host, open } = render({ flows: [FLOW, SUBFLOW] });
        const flowCard = card(host, 'Test Flow 1');

        chooseViewDetails(fixture, cardMenuButton(flowCard));

        expect(open).toHaveBeenCalledTimes(1);
        expect(open).toHaveBeenCalledWith(
            'Flow Details',
            {
                created_by: OWNER,
                created_at: '2026-03-12T13:28:23Z',
                last_edited_by: EDITOR,
                last_edited_at: '2026-09-02T12:40:19Z',
            },
            cardMenuButton(flowCard)
        );
    });

    it('is offered to a user who can only read flows', () => {
        const { fixture, host, open } = render({ flows: [FLOW], canWrite: false });

        chooseViewDetails(fixture, cardMenuButton(card(host, 'Test Flow 1')));

        expect(open).toHaveBeenCalledWith(
            'Flow Details',
            expect.objectContaining({ created_by: OWNER }),
            expect.anything()
        );
    });

    it('maps authorship the flow lacks to null', () => {
        const { fixture, host, open } = render({ flows: [FLOW_WITHOUT_AUTHORSHIP] });
        const flowCard = card(host, 'Legacy');

        chooseViewDetails(fixture, cardMenuButton(flowCard));

        expect(open).toHaveBeenCalledWith(
            'Flow Details',
            { created_by: null, created_at: null, last_edited_by: null, last_edited_at: null },
            cardMenuButton(flowCard)
        );
    });

    it("shows a subflow row's own authorship from its list entry, closing back to the row's ⋮ button", () => {
        const { fixture, host, open, getGraphLightById } = render({ flows: [FLOW, SUBFLOW] });
        const flowCard = card(host, 'Test Flow 1');
        expandSubflows(fixture, flowCard);

        chooseViewDetails(fixture, subflowMenuButton(flowCard));

        expect(getGraphLightById).not.toHaveBeenCalled();
        expect(open).toHaveBeenCalledWith(
            'Flow Details',
            { created_by: EDITOR, created_at: '2026-04-01T08:00:00Z', last_edited_by: null, last_edited_at: null },
            subflowMenuButton(flowCard)
        );
    });

    it('fetches the light graph of a subflow that is not in the list (hidden by the label filter)', () => {
        const fetched: GetGraphLightRequest = { ...SUBFLOW, created_by: OWNER };
        const { fixture, host, open, getGraphLightById, getGraphById } = render({
            flows: [FLOW],
            fetchedFlow: of(fetched),
        });
        const flowCard = card(host, 'Test Flow 1');
        expandSubflows(fixture, flowCard);

        chooseViewDetails(fixture, subflowMenuButton(flowCard));

        expect(getGraphLightById).toHaveBeenCalledWith(366);
        expect(getGraphById).not.toHaveBeenCalled();
        expect(open).toHaveBeenCalledWith(
            'Flow Details',
            { created_by: OWNER, created_at: '2026-04-01T08:00:00Z', last_edited_by: null, last_edited_at: null },
            subflowMenuButton(flowCard)
        );
    });

    it('reports a failed fetch instead of opening an empty dialog', () => {
        const { fixture, host, open, toastError } = render({
            flows: [FLOW],
            fetchedFlow: throwError(() => new Error('offline')),
        });
        const flowCard = card(host, 'Test Flow 1');
        expandSubflows(fixture, flowCard);

        chooseViewDetails(fixture, subflowMenuButton(flowCard));

        expect(open).not.toHaveBeenCalled();
        expect(toastError).toHaveBeenCalledWith('Failed to load details of flow "Subflow 1"');
    });
});
