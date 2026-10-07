import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LlmLibraryModel, ModelTypes } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { LlmLibraryCardComponent, LlmLibraryCardViewDetailsEvent } from './llm-library-card.component';

const MODEL: LlmLibraryModel = {
    id: 7,
    customName: 'gpt-4.1-chat',
    modelName: 'gpt-4.1',
    tags: [],
    temperature: 0.7,
    usedByCount: null,
    configType: ModelTypes.LLM,
    isDeprecated: false,
};

function render(canWrite: boolean): {
    fixture: ComponentFixture<LlmLibraryCardComponent>;
    overlay: HTMLElement;
    emitted: LlmLibraryCardViewDetailsEvent[];
} {
    TestBed.configureTestingModule({
        providers: [{ provide: PermissionsService, useValue: { can: () => canWrite } }],
    });
    const fixture = TestBed.createComponent(LlmLibraryCardComponent);
    fixture.componentRef.setInput('model', MODEL);
    const emitted: LlmLibraryCardViewDetailsEvent[] = [];
    fixture.componentInstance.viewDetailsClick.subscribe((event) => emitted.push(event));
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, overlay, emitted };
}

function moreButton(host: HTMLElement): HTMLButtonElement {
    return host.querySelector<HTMLButtonElement>('[aria-label="More actions"]')!;
}

function viewDetailsItem(overlay: HTMLElement): HTMLButtonElement | null {
    return overlay.querySelector<HTMLButtonElement>('[role="menuitem"]');
}

// The menu's own behaviour (keyboard, Escape, focus restore) is covered by ConfigCardMoreMenuComponent's spec.
describe('LlmLibraryCardComponent more menu', () => {
    it('places the ⋮ button before the edit and delete buttons', () => {
        const { fixture } = render(true);
        const buttons = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button'));

        expect(buttons).toHaveLength(3);
        expect(buttons[0]).toBe(moreButton(fixture.nativeElement));
    });

    it('emits viewDetailsClick with the model and its trigger when "View Details" is chosen', () => {
        const { fixture, overlay, emitted } = render(true);
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        expect(emitted).toEqual([{ model: MODEL, trigger }]);
    });

    it('offers "View Details" to a user who can only read configurations', () => {
        const { fixture, overlay } = render(false);
        const host = fixture.nativeElement as HTMLElement;

        expect(host.querySelectorAll('button')).toHaveLength(1);
        moreButton(host).click();
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)).not.toBeNull();
    });
});
