import { TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { BinnedWebhookTrigger, WebhookTriggerModel } from '../../models/webhook-trigger/webhook-trigger.model';
import { WebhookTriggerService } from '../../services/webhook-trigger/webhook-trigger.service';
import { WebhookTriggerSelectComponent } from './webhook-trigger-select.component';

const TRIGGER: WebhookTriggerModel = {
    id: 12,
    path: 'orders',
    provider_type: 'ngrok',
    ngrok_config: { name: 'Orders tunnel' } as WebhookTriggerModel['ngrok_config'],
    localhost_config: null,
};
const BINNED: BinnedWebhookTrigger = { id: 40, name: 'old-orders' };

function render(
    canReadWebhooks: boolean,
    selectedId = 12,
    binList: Observable<BinnedWebhookTrigger[]> = of([BINNED]),
    readonly = false
) {
    const list = vi.fn().mockReturnValue(of([TRIGGER]));
    const listInRecycleBin = vi.fn().mockReturnValue(binList);
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can: () => canReadWebhooks } },
            {
                provide: WebhookTriggerService,
                useValue: { list, listInRecycleBin, changed$: new Subject<void>() },
            },
        ],
    });
    const fixture = TestBed.createComponent(WebhookTriggerSelectComponent);
    fixture.componentRef.setInput('readonly', readonly);
    const onChange = vi.fn();
    fixture.componentInstance.registerOnChange(onChange);
    fixture.componentInstance.writeValue(selectedId);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const button = element.querySelector<HTMLButtonElement>('.wts__trigger')!;
    return { fixture, component: fixture.componentInstance, list, listInRecycleBin, onChange, button, element };
}

/** The note as a reader sees it: the template's line breaks collapse to single spaces. */
function noteText(element: HTMLElement): string | undefined {
    return element.querySelector('.wts__note')?.textContent?.replace(/\s+/g, ' ').trim();
}

describe('WebhookTriggerSelectComponent', () => {
    it('never lists triggers without Webhooks:Read and shows the current one by id, read-only', () => {
        const { component, list, button } = render(false);

        expect(list).not.toHaveBeenCalled();
        expect(button.textContent?.trim()).toBe('Webhook trigger #12');
        expect(component.isReadonlyView()).toBe(true);
        expect(component.selectedId()).toBe(12);
    });

    it('lists triggers and shows the chosen one by name with Webhooks:Read', () => {
        const { component, list, listInRecycleBin, button } = render(true);

        expect(list).toHaveBeenCalledTimes(1);
        expect(listInRecycleBin).not.toHaveBeenCalled();
        expect(button.textContent?.trim()).toBe('Orders tunnel (ngrok)');
        expect(component.isReadonlyView()).toBe(false);
    });

    it('keeps a trigger in the recycle bin, names it, and says how to fix it', () => {
        const { component, onChange, button, element } = render(true, BINNED.id);

        expect(component.selectedId()).toBe(BINNED.id);
        expect(onChange).not.toHaveBeenCalled();
        expect(button.textContent?.trim()).toBe('old-orders (in the recycle bin)');
        expect(noteText(element)).toBe(
            'This trigger is in the recycle bin, so it gets no requests. Restore it from the Recycle Bin, or pick another one.'
        );
    });

    it('clears an id that is neither live nor in the recycle bin', () => {
        const { component, onChange } = render(true, 99);

        expect(component.selectedId()).toBeNull();
        expect(onChange).toHaveBeenCalledWith(null);
    });

    it('never asks the recycle bin without Webhooks:Read', () => {
        const { listInRecycleBin, button } = render(false, BINNED.id);

        expect(listInRecycleBin).not.toHaveBeenCalled();
        expect(button.textContent?.trim()).toBe(`Webhook trigger #${BINNED.id}`);
    });

    it('tells a read-only viewer the trigger is binned, without a fix they cannot make', () => {
        const { element } = render(true, BINNED.id, of([BINNED]), true);

        expect(noteText(element)).toBe('This trigger is in the recycle bin, so it gets no requests.');
    });

    it('shows the id, not the placeholder, while the recycle bin is being asked', () => {
        const pending = new Subject<BinnedWebhookTrigger[]>();
        const { component, button } = render(true, BINNED.id, pending);

        expect(component.selectedId()).toBe(BINNED.id);
        expect(button.textContent?.trim()).toBe(`Webhook trigger #${BINNED.id}`);
    });

    it('keeps the id when the recycle bin cannot be read', () => {
        const { component, onChange, button } = render(
            true,
            BINNED.id,
            throwError(() => new Error('offline'))
        );

        expect(component.selectedId()).toBe(BINNED.id);
        expect(onChange).not.toHaveBeenCalled();
        expect(button.textContent?.trim()).toBe(`Webhook trigger #${BINNED.id}`);
    });

    it('lets a trigger picked while the recycle bin is asked win over the late answer', () => {
        const pending = new Subject<BinnedWebhookTrigger[]>();
        const { fixture, component, button } = render(true, BINNED.id, pending);

        component.writeValue(TRIGGER.id!);
        pending.next([BINNED]);
        fixture.detectChanges();

        expect(component.selectedId()).toBe(TRIGGER.id);
        expect(component.selectedIsBinned()).toBe(false);
        expect(button.textContent?.trim()).toBe('Orders tunnel (ngrok)');
    });
});
