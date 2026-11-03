import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { APP_TOURS } from './app.tours';
import type { TourDefinition } from './core/guided-tour';
import { validateTourDefinitions } from './core/guided-tour/registry/validate-tour-definitions';

describe('APP_TOURS', () => {
    /** Built as the registry builds them: in an injection context, with the app's root services. */
    function buildAppTours(): TourDefinition[] {
        return APP_TOURS.map((createTour) => TestBed.runInInjectionContext(createTour));
    }

    beforeEach(() => {
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    });

    it('holds only valid tours, under distinct keys', () => {
        expect(validateTourDefinitions(buildAppTours()).problems).toEqual([]);
    });
});
