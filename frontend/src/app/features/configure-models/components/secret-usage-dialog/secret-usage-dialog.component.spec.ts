import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NodeType, SecretUsageNodeDto, SecretUsageResponse } from '@shared/models';

import { ConfigService } from '../../../../services/config';
import { SecretUsageDialogComponent } from './secret-usage-dialog.component';

const API_URL = 'http://api/';
const SECRET_ID = 3;
const FLOW_ID = 7;

function usageOf(nodes: SecretUsageNodeDto[]): SecretUsageResponse {
    return {
        readable_total: 1,
        hidden_total: 0,
        categories: [{ key: 'flows', items: [{ id: FLOW_ID, name: 'Billing', nodes }] }],
    };
}

const TWO_SAME_NAMED_NODES = usageOf([
    { id: 11, node_number: 1, name: 'Fetch', node_type: NodeType.PYTHON, code_field: null },
    { id: 12, node_number: 2, name: 'Fetch', node_type: NodeType.PYTHON, code_field: null },
]);

describe('SecretUsageDialogComponent', () => {
    let fixture: ComponentFixture<SecretUsageDialogComponent>;
    let element: HTMLElement;

    function open(response: SecretUsageResponse): void {
        TestBed.configureTestingModule({
            imports: [SecretUsageDialogComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: DIALOG_DATA, useValue: { secretId: SECRET_ID, secretName: 'STRIPE_KEY' } },
            ],
        });
        fixture = TestBed.createComponent(SecretUsageDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
        TestBed.inject(HttpTestingController).expectOne(`${API_URL}secrets/${SECRET_ID}/usage/`).flush(response);
        fixture.detectChanges();
        element.querySelector<HTMLElement>('.secret-usage-dialog__nodes-toggle')!.click();
        fixture.detectChanges();
    }

    /** The dialog's own "Open node" button, one per node row. */
    function openNodeButtons(): HTMLElement[] {
        return Array.from(element.querySelectorAll<HTMLElement>('button[aria-label="Open node"]'));
    }

    it('lists two same-named nodes as two rows and counts both', () => {
        open(TWO_SAME_NAMED_NODES);

        expect(element.querySelector('.secret-usage-dialog__nodes-toggle')!.textContent).toContain('2 nodes');
        expect(openNodeButtons()).toHaveLength(2);
    });

    it('opens the flow at the clicked node by its backend id', () => {
        const openWindow = vi.spyOn(window, 'open').mockReturnValue(null);
        open(TWO_SAME_NAMED_NODES);

        openNodeButtons()[1].click();

        expect(openWindow).toHaveBeenCalledWith(`/flows/${FLOW_ID}?nodeId=12`, '_blank');
    });
});
