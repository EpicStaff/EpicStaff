import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { CreateSurfaceRequest } from '../../../../../features/agent-definitions/models/surface.model';
import { SurfaceCardComponent } from '../../../../../features/agent-definitions/pages/agent-definitions-page/components/agent-detail/agent-surfaces-panel/surface-card/surface-card.component';
import { LocalSurfaceDialogComponent, LocalSurfaceDialogData } from './local-surface-dialog.component';

@Component({
    selector: 'app-surface-card',
    template: '',
    providers: [{ provide: SurfaceCardComponent, useExisting: SurfaceCardStubComponent }],
})
class SurfaceCardStubComponent {
    readonly knowledgeInvalid = signal(false);
    invalidAfterFlush = false;
    readonly flushPendingKnowledge = vi.fn(() => this.knowledgeInvalid.set(this.invalidAfterFlush));
    readonly buildCreateRequest = vi.fn(
        (): Partial<CreateSurfaceRequest> => ({ instructions: 'flushed', knowledge: [] })
    );
}

function render(): {
    close: ReturnType<typeof vi.fn>;
    dialog: LocalSurfaceDialogComponent;
    card: SurfaceCardStubComponent;
} {
    const close = vi.fn();
    const data: LocalSurfaceDialogData = { mode: 'create', inlineSurface: null, llmConfigId: null };
    TestBed.configureTestingModule({
        providers: [
            { provide: DialogRef, useValue: { close } },
            { provide: DIALOG_DATA, useValue: data },
        ],
    });
    TestBed.overrideComponent(LocalSurfaceDialogComponent, {
        set: { template: '<app-surface-card />', imports: [SurfaceCardStubComponent], providers: [] },
    });
    const fixture = TestBed.createComponent(LocalSurfaceDialogComponent);
    fixture.detectChanges();
    const card = fixture.debugElement.children[0].componentInstance as SurfaceCardStubComponent;
    return { close, dialog: fixture.componentInstance, card };
}

describe('LocalSurfaceDialogComponent onConfirm', () => {
    it('flushes the pending knowledge edit before building the payload', () => {
        const { close, dialog, card } = render();

        dialog.onConfirm();

        expect(card.flushPendingKnowledge).toHaveBeenCalledBefore(card.buildCreateRequest);
        expect(close).toHaveBeenCalledWith(expect.objectContaining({ instructions: 'flushed' }));
    });

    it('keeps the dialog open when the flushed knowledge config is invalid', () => {
        const { close, dialog, card } = render();
        card.invalidAfterFlush = true;

        dialog.onConfirm();

        expect(card.buildCreateRequest).not.toHaveBeenCalled();
        expect(close).not.toHaveBeenCalled();
    });
});
