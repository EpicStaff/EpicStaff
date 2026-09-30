import { TestBed } from '@angular/core/testing';
import { of, Subject } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { WebhookTriggerModel } from '../../models/webhook-trigger/webhook-trigger.model';
import { WebhookTriggerService } from '../../services/webhook-trigger/webhook-trigger.service';
import { WebhookTriggerSelectComponent } from './webhook-trigger-select.component';

const TRIGGER: WebhookTriggerModel = {
    id: 12,
    path: 'orders',
    provider_type: 'ngrok',
    ngrok_config: { name: 'Orders tunnel' } as WebhookTriggerModel['ngrok_config'],
    localhost_config: null,
};

function render(canReadWebhooks: boolean) {
    const list = vi.fn().mockReturnValue(of([TRIGGER]));
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can: () => canReadWebhooks } },
            { provide: WebhookTriggerService, useValue: { list, changed$: new Subject<void>() } },
        ],
    });
    const fixture = TestBed.createComponent(WebhookTriggerSelectComponent);
    fixture.componentInstance.writeValue(12);
    fixture.detectChanges();
    const button = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.wts__trigger')!;
    return { component: fixture.componentInstance, list, button };
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
        const { component, list, button } = render(true);

        expect(list).toHaveBeenCalledTimes(1);
        expect(button.textContent?.trim()).toBe('Orders tunnel (ngrok)');
        expect(component.isReadonlyView()).toBe(false);
    });
});
