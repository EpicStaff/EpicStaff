import { Dialog } from '@angular/cdk/dialog';
import { ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { ApplicationRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService, ConfirmationDialogService } from '@shared/components';
import { RealtimeChannel } from '@shared/models';
import { RealtimeChannelService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { AgentDefinitionsApiService } from '../../../agent-definitions/services/agent-definitions-api.service';
import { VoiceSettingsSectionComponent } from './voice-settings-section.component';

function channel(id: number, overrides: Partial<RealtimeChannel> = {}): RealtimeChannel {
    return {
        id,
        name: `Support line ${id}`,
        channel_type: 'twilio',
        token: `token-${id}`,
        realtime_agent: null,
        realtime_agent_definition: null,
        is_enabled: true,
        created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
        created_at: '2026-03-12T13:28:23Z',
        last_edited_by: null,
        last_edited_at: null,
        ...overrides,
    };
}

const CHANNEL = channel(8);

function configure(canWrite: boolean, channels: RealtimeChannel[], open?: ReturnType<typeof vi.fn>): void {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: RealtimeChannelService,
                useValue: { getChannels: () => of(channels), channelsChanged$: new Subject<void>() },
            },
            { provide: AgentDefinitionsApiService, useValue: { getAgentDefinitions: () => of([]) } },
            { provide: ConfirmationDialogService, useValue: {} },
            { provide: ToastService, useValue: {} },
            { provide: PermissionsService, useValue: { can: () => canWrite } },
            ...(open ? [{ provide: AuthorshipDetailsDialogService, useValue: { open } }] : []),
        ],
    });
}

function render(
    canWrite: boolean,
    channels: RealtimeChannel[] = [CHANNEL]
): {
    fixture: ComponentFixture<VoiceSettingsSectionComponent>;
    overlay: HTMLElement;
    open: ReturnType<typeof vi.fn>;
} {
    const open = vi.fn();
    configure(canWrite, channels, open);
    const fixture = TestBed.createComponent(VoiceSettingsSectionComponent);
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, overlay, open };
}

function moreButtons(host: HTMLElement): HTMLButtonElement[] {
    return Array.from(host.querySelectorAll<HTMLButtonElement>('[aria-label="More actions"]'));
}

function viewDetailsItem(overlay: HTMLElement): HTMLButtonElement | null {
    return overlay.querySelector<HTMLButtonElement>('[role="menuitem"]');
}

/** CDK menus read the legacy `keyCode`, which a synthetic `KeyboardEvent` cannot be constructed with. */
function pressKey(target: HTMLElement, key: string, keyCode: number): KeyboardEvent {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
    Object.defineProperty(event, 'keyCode', { get: () => keyCode });
    target.dispatchEvent(event);
    return event;
}

// jsdom has no ResizeObserver; the overflow directive behind the header's <app-button> only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

describe('VoiceSettingsSectionComponent "View Details"', () => {
    it('puts the ⋮ button before Edit and Delete', () => {
        const { fixture } = render(true);
        const actions = (fixture.nativeElement as HTMLElement).querySelectorAll('.channel-card__action');

        expect(Array.from(actions, (action) => action.getAttribute('title'))).toEqual(['More', 'Edit', 'Delete']);
    });

    it('offers "View Details" to a user who can only read voice channels', () => {
        const { fixture, overlay } = render(false);
        const host = fixture.nativeElement as HTMLElement;

        expect(host.querySelectorAll('.channel-card__action')).toHaveLength(1);
        moreButtons(host)[0].click();
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)?.textContent?.trim()).toBe('View Details');
    });

    it('marks the ⋮ button active while its menu is open', () => {
        const { fixture } = render(true);
        const trigger = moreButtons(fixture.nativeElement)[0];

        trigger.click();
        fixture.detectChanges();

        expect(trigger.classList).toContain('channel-card__action--active');
        expect(trigger.getAttribute('aria-expanded')).toBe('true');
    });

    it('opens "Channel Details" with the channel of the chosen row, closing back to its ⋮ button', () => {
        const second = channel(9, { created_by: null, created_at: null });
        const { fixture, overlay, open } = render(true, [CHANNEL, second]);
        const trigger = moreButtons(fixture.nativeElement)[1];

        trigger.click();
        fixture.detectChanges();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        expect(open).toHaveBeenCalledExactlyOnceWith('Channel Details', second, trigger);
        expect(viewDetailsItem(overlay)).toBeNull();
        expect(trigger.classList).not.toContain('channel-card__action--active');
    });
});

describe('VoiceSettingsSectionComponent "View Details" inside the Configure Models dialog', () => {
    function openHostDialog(): { dialog: Dialog; overlay: HTMLElement; tick: () => void } {
        configure(true, [CHANNEL]);
        const dialog = TestBed.inject(Dialog);
        const appRef = TestBed.inject(ApplicationRef);
        const overlay = TestBed.inject(OverlayContainer).getContainerElement();
        dialog.open(VoiceSettingsSectionComponent);
        appRef.tick();
        return { dialog, overlay, tick: () => appRef.tick() };
    }

    it('closes only the menu on Escape, not the dialog hosting the section', () => {
        const { dialog, overlay, tick } = openHostDialog();
        const trigger = moreButtons(overlay)[0];

        trigger.click();
        tick();
        pressKey(viewDetailsItem(overlay)!, 'Escape', ESCAPE);
        tick();

        expect(viewDetailsItem(overlay)).toBeNull();
        expect(dialog.openDialogs).toHaveLength(1);
        expect(document.activeElement).toBe(trigger);
    });

    it('returns focus to the ⋮ button once the details dialog closes', () => {
        const { dialog, overlay, tick } = openHostDialog();
        const trigger = moreButtons(overlay)[0];

        trigger.click();
        tick();
        viewDetailsItem(overlay)!.click();
        tick();
        expect(dialog.openDialogs).toHaveLength(2);
        expect(trigger.contains(document.activeElement)).toBe(false);

        dialog.openDialogs[1].close();
        tick();

        expect(dialog.openDialogs).toHaveLength(1);
        expect(document.activeElement).toBe(trigger);
    });
});
