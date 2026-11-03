import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { of } from 'rxjs';

import { SessionOutputFile } from '../../../../../features/files/models/storage.models';
import { StorageApiService } from '../../../../../features/files/services/storage-api.service';
import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { SessionFilesButtonComponent } from './session-files-button.component';

const OUTPUT_FILES = [{ path: 'out/a.txt' }] as unknown as SessionOutputFile[];

describe('SessionFilesButtonComponent', () => {
    let fixture: ComponentFixture<SessionFilesButtonComponent>;

    function render(grantedActions: ActionCode[], files: SessionOutputFile[] = OUTPUT_FILES): HTMLElement {
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        TestBed.configureTestingModule({
            imports: [SessionFilesButtonComponent],
            providers: [
                { provide: StorageApiService, useValue: { getSessionOutputFiles: () => of(files) } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Files && grantedActions.includes(action),
                        canAny: () => false,
                    },
                },
            ],
        });
        fixture = TestBed.createComponent(SessionFilesButtonComponent);
        fixture.componentRef.setInput('sessionId', 'session-1');
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    afterEach(() => vi.unstubAllGlobals());

    it('shows the Files button when the user can export files', () => {
        const element = render([ActionCode.Export]);

        expect(element.querySelector('.session-files-btn')?.textContent).toContain('Files');
    });

    it('hides the Files button when the user can read but not export files', () => {
        const element = render([ActionCode.Read]);

        expect(element.querySelector('.session-files-btn')).toBeNull();
    });

    it('hides the Files button when the session has no output files', () => {
        const element = render([ActionCode.Export], []);

        expect(element.querySelector('.session-files-btn')).toBeNull();
    });
});
