import { Overlay, OverlayConfig } from '@angular/cdk/overlay';
import { EnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { TourStepView } from '../tour-renderer';
import { createCdkTourRenderer } from './cdk-tour-renderer';

const WELCOME: TourStepView = {
    content: { title: 'Welcome', body: [] },
    target: null,
    side: 'bottom',
    floating: 'center',
    buttons: { next: 'Next', back: false, skip: false, close: true },
    progress: null,
};

describe('CdkTourRenderer', () => {
    afterEach(() => vi.restoreAllMocks());

    /** Real CDK overlays, except that the given one (1-based, in creation order) fails to attach its content. */
    function failAttachingOverlay(failingOverlay: number): void {
        const overlay = TestBed.inject(Overlay);
        const createOverlay = overlay.create.bind(overlay);
        let createdOverlays = 0;
        vi.spyOn(overlay, 'create').mockImplementation((config?: OverlayConfig) => {
            const overlayRef = createOverlay(config);
            createdOverlays++;
            if (createdOverlays === failingOverlay) {
                vi.spyOn(overlayRef, 'attach').mockImplementation(() => {
                    throw new Error('The overlay content could not be attached');
                });
            }
            return overlayRef;
        });
    }

    it('leaves no dimmed layer behind when the popover fails to attach after the spotlight', () => {
        // The spotlight overlay is created first, the popover's second.
        failAttachingOverlay(2);
        const renderer = createCdkTourRenderer(TestBed.inject(EnvironmentInjector));

        expect(() => renderer.show(WELCOME)).toThrow('The overlay content could not be attached');

        expect(document.querySelector('app-tour-spotlight')).toBeNull();
        expect(() => renderer.dispose()).not.toThrow();
    });
});
