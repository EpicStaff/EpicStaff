import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../../services/auth/profile.service';
import { ConfigService } from '../../../../../../services/config';
import { FlowHeaderComponent } from './flow-header.component';

describe('FlowHeaderComponent', () => {
    let fixture: ComponentFixture<FlowHeaderComponent>;

    beforeEach(() => {
        // jsdom has no ResizeObserver; CollapseOnOverflowDirective needs one.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe = vi.fn();
                unobserve = vi.fn();
                disconnect = vi.fn();
            }
        );

        TestBed.configureTestingModule({
            imports: [FlowHeaderComponent],
            providers: [
                provideRouter([]),
                {
                    provide: PermissionsService,
                    useValue: { can: () => true, canAny: () => true } as unknown as PermissionsService,
                },
                {
                    provide: ProfileService,
                    useValue: { currentUserSignal: signal(null) } as unknown as ProfileService,
                },
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });

        fixture = TestBed.createComponent(FlowHeaderComponent);
        fixture.componentRef.setInput('isPreviewMode', true);
        fixture.detectChanges();
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    function tooltipHostOf(buttonSelector: string): HTMLElement {
        const button = fixture.nativeElement.querySelector(buttonSelector) as HTMLButtonElement;
        expect(button.disabled).toBe(true);
        const host = button.parentElement as HTMLElement;
        expect(host.classList).toContain('tooltip-host');
        return host;
    }

    it.each([
        ['.sessions-button', 'Exit preview mode to view sessions'],
        ['.get-curl-button', 'Exit preview mode to get the cURL command'],
        ['.save-split-btn__main', 'Exit preview mode to save'],
        ['.save-split-btn__chevron', 'Exit preview mode to save'],
        ['.run-button', 'Exit preview mode to run the flow'],
    ])('in preview, the disabled %s has a hoverable tooltip host', (buttonSelector, message) => {
        const host = tooltipHostOf(buttonSelector);
        const tooltipHost = fixture.debugElement
            .queryAll(By.directive(MatTooltip))
            .find((debugElement) => debugElement.nativeElement === host);
        const tooltip = tooltipHost!.injector.get(MatTooltip);
        const showSpy = vi.spyOn(tooltip, 'show');

        host.dispatchEvent(new MouseEvent('mouseenter'));

        expect(tooltip.message).toBe(message);
        expect(showSpy).toHaveBeenCalled();
        // The disabled button lets the pointer through (proves the component styles are applied here)...
        expect(getComputedStyle(host.querySelector(buttonSelector)!).pointerEvents).toBe('none');
        // ...while the tooltip host and its container stay hoverable.
        expect(getComputedStyle(host).pointerEvents).not.toBe('none');
        expect(getComputedStyle(host.closest('.save-split-btn') ?? host).pointerEvents).not.toBe('none');
    });

    it('spells cURL in the button label', () => {
        const label = fixture.nativeElement.querySelector('.get-curl-button .btn-label') as HTMLElement;

        expect(label.textContent?.trim()).toBe('Get cURL');
    });
});

describe('FlowHeaderComponent Run and Get cURL buttons', () => {
    beforeEach(() => {
        // jsdom has no ResizeObserver; CollapseOnOverflowDirective needs one.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe = vi.fn();
                unobserve = vi.fn();
                disconnect = vi.fn();
            }
        );
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    function render(granted: ActionCode[]): HTMLElement {
        const can = (resource: ResourceCode, action: ActionCode): boolean =>
            resource === ResourceCode.Flows && granted.includes(action);
        TestBed.configureTestingModule({
            imports: [FlowHeaderComponent],
            providers: [
                provideRouter([]),
                {
                    provide: PermissionsService,
                    useValue: {
                        can,
                        canAny: (resource: ResourceCode, actions: ActionCode[]) =>
                            actions.some((action) => can(resource, action)),
                    } as unknown as PermissionsService,
                },
                {
                    provide: ProfileService,
                    useValue: { currentUserSignal: signal(null) } as unknown as ProfileService,
                },
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        const fixture = TestBed.createComponent(FlowHeaderComponent);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it('are shown to a user who can run flows, even without edit rights', () => {
        const host = render([ActionCode.Read, ActionCode.Use]);

        expect(host.querySelector('.run-button')).not.toBeNull();
        expect(host.querySelector('.get-curl-button')).not.toBeNull();
        expect(host.querySelector('.save-split-btn')).toBeNull();
    });

    it('are hidden from a user who cannot run flows, while their edit controls stay', () => {
        const host = render([ActionCode.Read, ActionCode.Update]);

        expect(host.querySelector('.run-button')).toBeNull();
        expect(host.querySelector('.get-curl-button')).toBeNull();
        expect(host.querySelector('.save-split-btn')).not.toBeNull();
    });
});
