import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';
import { EMPTY } from 'rxjs';

import { TransferJob } from '../../../../core/models/transfer-job.model';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { FilesSearchService } from '../../../files/services/files-search.service';
import { CollectionStatus, GetCollectionRequest } from '../../models/collection.model';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { KnowledgeSourcesPollingService } from '../../services/knowledge-sources-polling.service';
import { CollectionsListPageComponent } from './collections-list-page.component';
import { CollectionDetailsComponent } from './components/collection-details/collection-details.component';

const COLLECTIONS_URL = '/api/source-collections/';
const EXPORT_JOBS_URL = '/api/source-collections/export-jobs/';
const JOB_URL = '/api/transfer-jobs/job-1/';
const TICKET_URL = '/api/transfer-jobs/job-1/download-ticket/';
const DOWNLOAD_URL = '/api/transfer-jobs/job-1/download/?ticket=t-1';

function collection(id: number, name: string, createdAt: string): GetCollectionRequest {
    return {
        collection_id: id,
        collection_name: name,
        description: null,
        status: CollectionStatus.EMPTY,
        document_count: 0,
        rag_configurations: [],
        created_at: createdAt,
        updated_at: createdAt,
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    };
}

// Newest first, as the list shows them.
const MANUALS = collection(1, 'Manuals', '2026-11-02T10:00:00Z');
const POLICIES = collection(2, 'Policies', '2026-11-01T10:00:00Z');

function transferJob(overrides: Partial<TransferJob>): TransferJob {
    return {
        id: 'job-1',
        kind: 'export',
        main_entity: 'SourceCollection',
        status: 'running',
        file_name: null,
        result: null,
        error: null,
        created_at: '2026-11-06T10:00:00Z',
        finished_at: null,
        expires_at: null,
        ...overrides,
    } as TransferJob;
}

let httpMock: HttpTestingController;
let fixture: ComponentFixture<CollectionsListPageComponent>;
let dialogOpen: ReturnType<typeof vi.fn>;
let toastError: ReturnType<typeof vi.fn>;
let clickedLinks: string[];

// jsdom has no ResizeObserver; the buttons' collapse-on-overflow only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Renders the Knowledge Sources list with these collections, for a user granted these actions. */
function renderPage(
    collections: GetCollectionRequest[],
    granted: ActionCode[] = [ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Export]
): void {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    dialogOpen = vi.fn(() => ({ closed: EMPTY }));
    toastError = vi.fn();
    clickedLinks = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
        clickedLinks.push(this.href);
    });
    const can = (resource: ResourceCode, action: ActionCode): boolean =>
        resource === ResourceCode.KnowledgeSources && granted.includes(action);

    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            provideHttpClient(),
            provideHttpClientTesting(),
            FilesSearchService,
            { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            {
                provide: PermissionsService,
                useValue: {
                    can,
                    canAny: (resource: ResourceCode, actions: ActionCode[]) =>
                        actions.some((action) => can(resource, action)),
                },
            },
            { provide: Dialog, useValue: { open: dialogOpen } },
            {
                provide: ToastService,
                useValue: {
                    error: toastError,
                    success: vi.fn(),
                },
            },
            // Polls collection details every few seconds; not what is under test.
            { provide: KnowledgeSourcesPollingService, useValue: { startPagePolling() {}, stopPagePolling() {} } },
        ],
    });
    // The open collection's panel brings its own services; the list beside it is under test.
    TestBed.overrideComponent(CollectionsListPageComponent, {
        remove: { imports: [CollectionDetailsComponent] },
        add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
    });
    httpMock = TestBed.inject(HttpTestingController);
    // Already loaded once, as after a visit to the page: the list then shows without the first load's delay.
    TestBed.inject(CollectionsStorageService).setCollections(collections);

    fixture = TestBed.createComponent(CollectionsListPageComponent);
    fixture.detectChanges();
    httpMock.expectOne(COLLECTIONS_URL).flush(collections);
}

async function settle(): Promise<void> {
    await vi.waitFor(() => {
        fixture.detectChanges();
        expect(host().querySelector('app-collections-list-sidebar')).not.toBeNull();
    });
}

function host(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

function buttonLabelled(label: string): HTMLButtonElement | undefined {
    return [...host().querySelectorAll('button')].find(
        (button) => button.getAttribute('aria-label') === label || button.textContent?.trim() === label
    );
}

function click(label: string): void {
    const button = buttonLabelled(label);
    expect(button, `a "${label}" button`).toBeDefined();
    button!.click();
    fixture.detectChanges();
}

function cardNamed(name: string): HTMLElement {
    const card = [...host().querySelectorAll<HTMLElement>('app-collection')].find((candidate) =>
        candidate.textContent?.includes(name)
    );
    expect(card, `a "${name}" card`).toBeDefined();
    return card!;
}

function shownCollectionNames(): string[] {
    return [...host().querySelectorAll('app-collection .name')].map((name) => name.textContent!.trim());
}

/** Lets the export job finish and hands out its download link. */
async function completeExportJob(): Promise<void> {
    (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush(
        transferJob({ status: 'completed', file_name: 'collections.zip', result: { excluded: [] } })
    );
    httpMock.expectOne(TICKET_URL).flush({ download_url: DOWNLOAD_URL });
}

/** Opens a card's ⋮ menu; its items render in an overlay. */
function openCardMenu(name: string): void {
    click(`More actions for ${name}`);
}

function menuItem(label: string): HTMLButtonElement | undefined {
    return [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(
        (item) => item.textContent?.trim() === label
    );
}

function clickMenuItem(label: string): void {
    const item = menuItem(label);
    expect(item, `a "${label}" menu item`).toBeDefined();
    item!.click();
    fixture.detectChanges();
}

function exportFromCard(name: string): void {
    openCardMenu(name);
    clickMenuItem('Export');
}

function typeInSidebarSearch(term: string): void {
    const field = host().querySelector<HTMLInputElement>('input[aria-label="Search collections"]');
    expect(field, 'the sidebar search').not.toBeNull();
    field!.value = term;
    field!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

function headerSearch(term: string): void {
    TestBed.inject(FilesSearchService).setSearchTerm(term);
    fixture.detectChanges();
}

/** The export control's menu button: the chevron, or in select mode the selected count. */
function openSelectionMenu(): void {
    const trigger = [...host().querySelectorAll('button')].find((button) =>
        /selection options$/i.test(button.getAttribute('aria-label') ?? '')
    );
    expect(trigger, 'the selection menu button').toBeDefined();
    trigger!.click();
    fixture.detectChanges();
}

/** The selected count the export control shows in select mode; null outside it. */
function selectedCount(): number | null {
    const count = [...host().querySelectorAll('button')].find((button) =>
        button.getAttribute('aria-label')?.startsWith('Selected ')
    );
    return count ? Number(count.textContent!.trim()) : null;
}

function checkboxesShown(): number {
    return host().querySelectorAll('app-collection app-checkbox').length;
}

afterEach(() => {
    httpMock.verify();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

describe('CollectionsListPageComponent export', () => {
    it('exports a collection from its card menu as a job and downloads the archive through a ticket', async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();

        exportFromCard('Policies');

        const start = httpMock.expectOne(EXPORT_JOBS_URL);
        expect(start.request.body).toEqual({ ids: [2] });
        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        await completeExportJob();

        expect(clickedLinks).toEqual([new URL(DOWNLOAD_URL, document.baseURI).href]);
        expect(toastError).not.toHaveBeenCalled();
        // The card's menu does not open the collection.
        expect(cardNamed('Policies').querySelector('.collection.selected')).toBeNull();
    });

    it("disables a card's Export while its export runs, so a second click starts no second job", async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();

        exportFromCard('Policies');
        httpMock.expectOne(EXPORT_JOBS_URL).flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        fixture.detectChanges();

        openCardMenu('Policies');
        expect(menuItem('Export')).toBeUndefined();
        expect(menuItem('Exporting…')!.getAttribute('aria-disabled')).toBe('true');
        menuItem('Exporting…')!.click();
        httpMock.expectNone(EXPORT_JOBS_URL);
        document.body.click();
        fixture.detectChanges();

        openCardMenu('Manuals');
        expect(menuItem('Export')!.getAttribute('aria-disabled')).not.toBe('true');
        document.body.click();
        fixture.detectChanges();

        await completeExportJob();
        fixture.detectChanges();
        openCardMenu('Policies');
        expect(menuItem('Export')).toBeDefined();
    });

    it("reports a failed export job with the server's reason and downloads nothing", async () => {
        renderPage([MANUALS]);
        await settle();

        exportFromCard('Manuals');
        httpMock.expectOne(EXPORT_JOBS_URL).flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush(
            transferJob({ status: 'failed', error: { code: 'export_failed', message: 'Storage is unavailable.' } })
        );

        expect(toastError).toHaveBeenCalledExactlyOnceWith('Storage is unavailable.');
        expect(clickedLinks).toEqual([]);
    });
});

describe('CollectionsListPageComponent bulk selection', () => {
    const PROCEDURES = collection(4, 'Procedures', '2026-10-31T10:00:00Z');

    it('enters select mode from Export collections: checkboxes on the cards, the count, cancel and confirm', async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();
        expect(checkboxesShown()).toBe(0);
        expect(selectedCount()).toBeNull();

        click('Export collections');

        expect(checkboxesShown()).toBe(2);
        expect(selectedCount()).toBe(0);
        expect(buttonLabelled('Cancel selection')).toBeDefined();
        expect(buttonLabelled('Export selected')).toBeDefined();
        expect(buttonLabelled('Export collections')).toBeUndefined();
    });

    it('counts the picks and exports them all in one job with confirm, then leaves select mode', async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();

        click('Export collections');
        cardNamed('Manuals').click();
        cardNamed('Policies').click();
        fixture.detectChanges();
        expect(selectedCount()).toBe(2);
        click('Export selected');

        const start = httpMock.expectOne(EXPORT_JOBS_URL);
        expect(start.request.body).toEqual({ ids: [1, 2] });
        fixture.detectChanges();
        expect(checkboxesShown()).toBe(0);
        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        await completeExportJob();

        expect(clickedLinks).toHaveLength(1);
    });

    it('does nothing on confirm while nothing is picked', async () => {
        renderPage([MANUALS]);
        await settle();

        click('Export collections');
        expect(buttonLabelled('Export selected')!.getAttribute('aria-disabled')).toBe('true');
        click('Export selected');

        httpMock.expectNone(EXPORT_JOBS_URL);
        expect(checkboxesShown()).toBe(1);
    });

    it('leaves select mode with cancel, dropping the picks and exporting nothing', async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();
        click('Export collections');
        cardNamed('Manuals').click();
        fixture.detectChanges();

        click('Cancel selection');

        expect(checkboxesShown()).toBe(0);
        expect(buttonLabelled('Export collections')).toBeDefined();
        httpMock.expectNone(EXPORT_JOBS_URL);
        click('Export collections');
        expect(selectedCount()).toBe(0);
    });

    it('enters select mode from the menu, with Select or Select all', async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();

        openSelectionMenu();
        clickMenuItem('Select all');

        expect(checkboxesShown()).toBe(2);
        expect(selectedCount()).toBe(2);

        click('Cancel selection');
        openSelectionMenu();
        clickMenuItem('Select');
        expect(checkboxesShown()).toBe(2);
        expect(selectedCount()).toBe(0);
    });

    it('selects all shown collections without dropping a pick the search hides', async () => {
        renderPage([MANUALS, POLICIES, PROCEDURES]);
        await settle();
        click('Export collections');
        cardNamed('Manuals').click();
        fixture.detectChanges();

        typeInSidebarSearch('P');
        openSelectionMenu();
        clickMenuItem('Select all');
        // Manuals is picked but hidden: neither counted nor exported.
        expect(selectedCount()).toBe(2);

        typeInSidebarSearch('');
        expect(selectedCount()).toBe(3);
    });

    it('deselects only the shown collections', async () => {
        renderPage([MANUALS, POLICIES, PROCEDURES]);
        await settle();
        click('Export collections');
        cardNamed('Manuals').click();
        cardNamed('Policies').click();
        fixture.detectChanges();

        typeInSidebarSearch('Pol');
        openSelectionMenu();
        clickMenuItem('Deselect all');
        typeInSidebarSearch('');

        expect(selectedCount()).toBe(1);
        click('Export selected');
        expect(httpMock.expectOne(EXPORT_JOBS_URL).request.body).toEqual({ ids: [1] });
    });

    it('leaves select mode when the last collection goes, so a refilled list starts outside it', async () => {
        renderPage([MANUALS]);
        await settle();
        click('Export collections');
        cardNamed('Manuals').click();
        fixture.detectChanges();

        const storage = TestBed.inject(CollectionsStorageService);
        storage.setCollections([]);
        fixture.detectChanges();
        storage.setCollections([MANUALS, POLICIES]);
        fixture.detectChanges();

        expect(checkboxesShown()).toBe(0);
        expect(selectedCount()).toBeNull();
        click('Export collections');
        expect(selectedCount()).toBe(0);
    });

    it('exports only the picks the list shows', async () => {
        renderPage([MANUALS, POLICIES, PROCEDURES]);
        await settle();
        click('Export collections');
        cardNamed('Manuals').click();
        cardNamed('Policies').click();
        fixture.detectChanges();

        headerSearch('Pol');
        click('Export selected');

        expect(httpMock.expectOne(EXPORT_JOBS_URL).request.body).toEqual({ ids: [2] });
    });
});

describe('CollectionsListPageComponent search', () => {
    const PROCEDURES = collection(4, 'Procedures', '2026-10-31T10:00:00Z');

    it.each([
        { term: 'pol', shown: ['Policies'] },
        { term: '  MAN ', shown: ['Manuals'] },
        { term: 'p', shown: ['Policies', 'Procedures'] },
        { term: '', shown: ['Manuals', 'Policies', 'Procedures'] },
    ])('shows the collections whose name contains "$term"', async ({ term, shown }) => {
        renderPage([MANUALS, POLICIES, PROCEDURES]);
        await settle();

        typeInSidebarSearch(term);

        expect(shownCollectionNames()).toEqual(shown);
    });

    it('says so when no collection matches', async () => {
        renderPage([MANUALS, POLICIES]);
        await settle();

        typeInSidebarSearch('zzz');

        expect(shownCollectionNames()).toEqual([]);
        expect(host().textContent).toContain('No collections match');
    });

    it("narrows the list together with the page header's search", async () => {
        renderPage([MANUALS, POLICIES, PROCEDURES]);
        await settle();

        typeInSidebarSearch('p');
        headerSearch('olic');

        expect(shownCollectionNames()).toEqual(['Policies']);
    });
});

describe('CollectionsListPageComponent permissions', () => {
    it('offers no export, on a card or for a selection, without the export permission', async () => {
        renderPage([MANUALS], [ActionCode.Read, ActionCode.Create, ActionCode.Update]);
        await settle();

        expect(buttonLabelled('More actions for Manuals')).toBeUndefined();
        expect(buttonLabelled('Export collections')).toBeUndefined();
        expect(buttonLabelled('Selection options')).toBeUndefined();
    });

    it('offers export with the export permission alone', async () => {
        renderPage([MANUALS], [ActionCode.Read, ActionCode.Export]);
        await settle();

        expect(buttonLabelled('More actions for Manuals')).toBeDefined();
        expect(buttonLabelled('Export collections')).toBeDefined();
    });
});
