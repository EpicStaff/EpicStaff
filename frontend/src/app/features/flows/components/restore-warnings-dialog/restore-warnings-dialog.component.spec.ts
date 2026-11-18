import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RestoreWarning } from '../../models/graph.model';
import { RestoreWarningsDialogComponent, RestoreWarningsDialogData } from './restore-warnings-dialog.component';

// jsdom has no ResizeObserver; app-button's collapse directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const DELETED_AGENT: RestoreWarning = {
    type: 'fk_nulled',
    node_name: 'Writer',
    node_id: 3,
    reason: 'agent 9 no longer exists',
};

function capped(overrides: Partial<RestoreWarning> = {}): RestoreWarning {
    return {
        type: 'storage_grant_capped',
        node_name: 'Fetch data',
        node_type: 'python-node',
        node_id: 11,
        field: 'python_code',
        dropped_grants: ['delete'],
        missing_permissions: ['Files: Delete'],
        ...overrides,
    };
}

describe('RestoreWarningsDialogComponent', () => {
    let fixture: ComponentFixture<RestoreWarningsDialogComponent>;
    let close: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        close = vi.fn();
    });

    afterEach(() => vi.unstubAllGlobals());

    function open(warnings: RestoreWarning[]): void {
        const data: RestoreWarningsDialogData = { warnings };
        TestBed.configureTestingModule({
            imports: [RestoreWarningsDialogComponent],
            providers: [
                { provide: DialogRef, useValue: { close } as unknown as DialogRef },
                { provide: DIALOG_DATA, useValue: data },
            ],
        });
        fixture = TestBed.createComponent(RestoreWarningsDialogComponent);
        fixture.detectChanges();
    }

    const root = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const title = (): string => root().querySelector('.dialog-title')?.textContent?.trim() ?? '';
    const message = (): string => root().querySelector('.dialog-message')?.textContent ?? '';
    const items = (): string[] =>
        Array.from(root().querySelectorAll('.warning-item')).map((item) =>
            (item.textContent ?? '').replace(/\s+/g, ' ').trim()
        );

    it('names the node and the unticked box for a capped warning, with a header that fits', () => {
        open([capped()]);

        expect(title()).toBe('Storage Permissions Reduced');
        expect(message()).not.toContain('deleted');
        expect(items()).toEqual(["Fetch data: Delete unticked — you don't have Files: Delete"]);
    });

    it('lists every dropped box and missing permission', () => {
        open([
            capped({ dropped_grants: ['write', 'delete'], missing_permissions: ['Files: Create', 'Files: Delete'] }),
        ]);

        expect(items()).toEqual(["Fetch data: Write, Delete unticked — you don't have Files: Create, Files: Delete"]);
    });

    it.each([
        ['pre_python_code', 'pre-computation'],
        ['post_python_code', 'post-computation'],
    ])('says which code of a Classification Decision Table lost its box (%s)', (field, slot) => {
        open([capped({ node_name: 'Classifier', field })]);

        expect(items()).toEqual([`Classifier: Delete unticked in ${slot} code — you don't have Files: Delete`]);
    });

    it('keeps the missing-dependencies header and text for the existing warning types', () => {
        open([DELETED_AGENT]);

        expect(title()).toBe('Missing Dependencies');
        expect(items()).toEqual(['In node Writer, agent 9 no longer exists']);
    });

    it('shows both kinds under a header that covers them', () => {
        open([DELETED_AGENT, capped()]);

        expect(title()).toBe('Restore Warnings');
        expect(message()).toContain('dependencies');
        expect(message()).toContain('unticked');
        expect(items()).toEqual([
            'In node Writer, agent 9 no longer exists',
            "Fetch data: Delete unticked — you don't have Files: Delete",
        ]);
    });

    it('closes with the restored node id when a capped warning is clicked', () => {
        open([capped()]);

        root().querySelector<HTMLButtonElement>('.warning-item--clickable')?.click();

        expect(close).toHaveBeenCalledExactlyOnceWith(11);
    });
});
