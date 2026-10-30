import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService, ConfirmationResult } from '@shared/components';
import { of, Subject } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { StorageTreeResponse, StorageUploadLimits, StorageUploadOutcome } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';
import { StorageUploadService } from '../../services/storage-upload.service';
import { CreateFolderDialogComponent } from './create-folder-dialog.component';

const EMPTY_STORAGE_TREE: StorageTreeResponse = {
    path: '',
    truncated: false,
    tree: {
        id: null,
        name: '',
        path: '',
        type: 'folder',
        size: 0,
        modified: null,
        children: [],
        created_at: null,
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    },
};

/** Class logic only: the component is built without its template. */
describe('CreateFolderDialogComponent dismissal', () => {
    let component: CreateFolderDialogComponent;
    let backdropClick: Subject<MouseEvent>;
    let keydownEvents: Subject<KeyboardEvent>;
    let close: ReturnType<typeof vi.fn>;
    let confirm: ReturnType<typeof vi.fn>;
    let confirmAnswer: Subject<ConfirmationResult>;
    let uploadOutcomes: Subject<StorageUploadOutcome>;

    beforeEach(() => {
        backdropClick = new Subject();
        keydownEvents = new Subject();
        close = vi.fn();
        confirmAnswer = new Subject();
        confirm = vi.fn(() => confirmAnswer);
        uploadOutcomes = new Subject();

        TestBed.configureTestingModule({
            providers: [
                {
                    provide: DialogRef,
                    useValue: { backdropClick, keydownEvents, close, disableClose: false } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: {} },
                {
                    provide: StorageApiService,
                    useValue: {
                        tree: () => of(EMPTY_STORAGE_TREE),
                        getUploadLimits: () => of(null),
                    } as unknown as StorageApiService,
                },
                {
                    provide: StorageUploadService,
                    useValue: {
                        uploadEach: () => uploadOutcomes,
                        confirmUploadPlan: (_targetPath: string, files: File[]) => of(files),
                    } as unknown as StorageUploadService,
                },
                { provide: ConfirmationDialogService, useValue: { confirm } as unknown as ConfirmationDialogService },
                { provide: ToastService, useValue: { error: vi.fn() } as unknown as ToastService },
            ],
        });
        component = TestBed.runInInjectionContext(() => new CreateFolderDialogComponent());
        component.ngOnInit();
    });

    function file(name: string): File {
        return new File(['content'], name, { type: 'text/plain' });
    }

    function pressEscape(init: KeyboardEventInit = {}): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true, ...init });
        keydownEvents.next(event);
        return event;
    }

    function startUpload(files: File[]): void {
        component.files.set(files);
        component.onConfirm();
        expect(component.isUploading()).toBe(true);
    }

    function landed(uploaded: File): void {
        uploadOutcomes.next({ ok: true, file: uploaded, result: { type: 'file', path: uploaded.name, size: 7 } });
    }

    it('takes over closing from the dialog', () => {
        expect(TestBed.inject(DialogRef).disableClose).toBe(true);
    });

    it('closes on Escape at once when nothing is uploading, and consumes the key', () => {
        const event = pressEscape();

        expect(event.defaultPrevented).toBe(true);
        expect(confirm).not.toHaveBeenCalled();
        expect(close).toHaveBeenCalledWith();
    });

    it('ignores Escape with a modifier', () => {
        const event = pressEscape({ shiftKey: true });

        expect(event.defaultPrevented).toBe(false);
        expect(close).not.toHaveBeenCalled();
    });

    it.each([
        { label: 'backdrop click', dismiss: () => backdropClick.next(new MouseEvent('click')) },
        { label: 'Escape', dismiss: () => pressEscape() },
        { label: 'the Cancel button', dismiss: () => component.onCancel() },
    ])('asks before closing on $label while uploading', ({ dismiss }) => {
        startUpload([file('a.txt')]);

        dismiss();

        expect(confirm).toHaveBeenCalledTimes(1);
        expect(close).not.toHaveBeenCalled();
    });

    it('asks only once while the question is open', () => {
        startUpload([file('a.txt')]);

        backdropClick.next(new MouseEvent('click'));
        pressEscape();

        expect(confirm).toHaveBeenCalledTimes(1);
    });

    it('stays open and keeps uploading when the user declines', () => {
        startUpload([file('a.txt')]);
        backdropClick.next(new MouseEvent('click'));

        confirmAnswer.next(false);

        expect(close).not.toHaveBeenCalled();
        expect(component.isUploading()).toBe(true);
    });

    it('reports the files that landed so far when the user closes anyway', () => {
        const first = file('a.txt');
        startUpload([first, file('b.txt'), file('c.txt')]);
        landed(first);

        backdropClick.next(new MouseEvent('click'));
        confirmAnswer.next(true);

        expect(close).toHaveBeenCalledWith({ type: 'upload', count: 1 });
    });

    it('reports an upload even with nothing counted, so the opener reloads its tree', () => {
        startUpload([file('a.txt')]);

        pressEscape();
        confirmAnswer.next(true);

        expect(close).toHaveBeenCalledWith({ type: 'upload', count: 0 });
    });

    it('closes once the question is answered when the batch succeeded meanwhile', () => {
        const only = file('a.txt');
        startUpload([only]);
        backdropClick.next(new MouseEvent('click'));

        landed(only);
        uploadOutcomes.complete();
        expect(close).not.toHaveBeenCalled();

        confirmAnswer.next(false);
        expect(close).toHaveBeenCalledWith({ type: 'upload', count: 1 });
    });

    it('counts earlier attempts when a later dismissal closes the dialog', () => {
        const good = file('a.txt');
        const bad = file('b.txt');
        startUpload([good, bad]);
        landed(good);
        uploadOutcomes.next({ ok: false, file: bad, error: new Error('rejected') });
        uploadOutcomes.complete();
        expect(component.isUploading()).toBe(false);
        expect(component.files()).toEqual([bad]);

        pressEscape();

        expect(confirm).not.toHaveBeenCalled();
        expect(close).toHaveBeenCalledWith({ type: 'upload', count: 1 });
    });
});

describe('CreateFolderDialogComponent unpack badge', () => {
    const limits: StorageUploadLimits = {
        max_file_size: null,
        max_archive_size: 50 * 1024 * 1024,
        free_bytes: 1024 * 1024 * 1024,
        archive_suffixes: ['.tar.gz', '.tgz', '.txz', '.zip'],
        document_extensions: ['.docx'],
    };

    function create(uploadLimits: StorageUploadLimits | null): CreateFolderDialogComponent {
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: DialogRef,
                    useValue: {
                        backdropClick: new Subject(),
                        keydownEvents: new Subject(),
                        close: vi.fn(),
                        disableClose: false,
                    } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: {} },
                {
                    provide: StorageApiService,
                    useValue: {
                        tree: () => of(EMPTY_STORAGE_TREE),
                        getUploadLimits: () => of(uploadLimits),
                    } as unknown as StorageApiService,
                },
                { provide: StorageUploadService, useValue: {} as StorageUploadService },
                { provide: ConfirmationDialogService, useValue: {} as ConfirmationDialogService },
                { provide: ToastService, useValue: {} as ToastService },
            ],
        });
        return TestBed.runInInjectionContext(() => new CreateFolderDialogComponent());
    }

    function file(name: string): File {
        return new File(['content'], name);
    }

    it('follows the backend rule once the limits are known', () => {
        const component = create(limits);

        expect(component.isArchive(file('passwords.txt.gz'))).toBe(false);
        expect(component.isArchive(file('dump.sql.gz'))).toBe(false);
        expect(component.isArchive(file('bundle.txz'))).toBe(true);
        expect(component.isArchive(file('site.TAR.GZ'))).toBe(true);
        expect(component.isArchive(file('report.docx'))).toBe(false);
    });

    it('shows no archive badge while the limits are unknown', () => {
        const component = create(null);

        expect(component.isArchive(file('site.tar.gz'))).toBe(false);
        expect(component.isArchive(file('notes.txt'))).toBe(false);
    });
});

describe('CreateFolderDialogComponent file removal', () => {
    let fixture: ComponentFixture<CreateFolderDialogComponent>;

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const removeButtons = (): HTMLButtonElement[] =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('.create-folder-dialog__file-remove'));
    const chooseFilesButton = (): HTMLButtonElement => host().querySelector('.file-uploader__button')!;

    beforeEach(async () => {
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: DialogRef,
                    useValue: {
                        backdropClick: new Subject(),
                        keydownEvents: new Subject(),
                        close: vi.fn(),
                        disableClose: false,
                    } as unknown as DialogRef,
                },
                { provide: DIALOG_DATA, useValue: {} },
                {
                    provide: StorageApiService,
                    useValue: {
                        tree: () => of(EMPTY_STORAGE_TREE),
                        getUploadLimits: () => of(null),
                    } as unknown as StorageApiService,
                },
                { provide: StorageUploadService, useValue: {} as StorageUploadService },
                { provide: ConfirmationDialogService, useValue: {} as ConfirmationDialogService },
                { provide: ToastService, useValue: {} as ToastService },
            ],
        });
        fixture = TestBed.createComponent(CreateFolderDialogComponent);
        fixture.componentInstance.files.set(['a.txt', 'b.txt'].map((name) => new File(['content'], name)));
        fixture.autoDetectChanges();
        await fixture.whenStable();
    });

    async function removeWithKeyboard(button: HTMLButtonElement): Promise<void> {
        button.focus();
        button.click();
        await fixture.whenStable();
    }

    it('keeps the focus on the next Remove button, then on the file picker once the list is empty', async () => {
        await removeWithKeyboard(removeButtons()[0]);

        expect(removeButtons().map((button) => button.getAttribute('aria-label'))).toEqual(['Remove b.txt']);
        expect(document.activeElement).toBe(removeButtons()[0]);

        await removeWithKeyboard(removeButtons()[0]);

        expect(removeButtons()).toEqual([]);
        expect(document.activeElement).toBe(chooseFilesButton());
    });

    it('leaves the focus alone when the Remove button did not have it', async () => {
        const otherField = host().querySelector<HTMLInputElement>('.create-folder-dialog__input')!;
        otherField.focus();

        removeButtons()[0].click();
        await fixture.whenStable();

        expect(document.activeElement).toBe(otherField);
    });
});
