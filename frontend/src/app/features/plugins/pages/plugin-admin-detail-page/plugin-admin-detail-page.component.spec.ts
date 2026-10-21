import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { PluginDetail } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPackageReview, buildPluginDetail } from '../../testing/plugin-fixtures';
import { PluginAdminDetailPageComponent } from './plugin-admin-detail-page.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function withBackend(hasBackend: boolean): PluginDetail {
    const review = buildPackageReview({ review_state: 'approved' });
    return buildPluginDetail({
        current_package: { ...review, contents: { ...review.contents, has_backend: hasBackend } },
    });
}

describe('PluginAdminDetailPageComponent tabs', () => {
    let fixture: ComponentFixture<PluginAdminDetailPageComponent>;

    function render(plugin: PluginDetail): void {
        TestBed.configureTestingModule({
            imports: [PluginAdminDetailPageComponent],
            providers: [
                provideRouter([]),
                { provide: PluginsAdminStorageService, useValue: { getPlugin: () => of(plugin) } },
                { provide: PluginDialogsService, useValue: {} },
            ],
        });
        fixture = TestBed.createComponent(PluginAdminDetailPageComponent);
        fixture.componentRef.setInput('identifier', plugin.identifier);
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function tabLabels(): string[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.detail__tabs app-tab-button')).map(
            (tab) => tab.textContent?.trim() ?? ''
        );
    }

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

    afterEach(() => vi.unstubAllGlobals());

    it('offers Settings, Limits and Runtime for a plugin whose current package has a backend', () => {
        render(withBackend(true));

        expect(tabLabels()).toEqual(['Overview', 'Organizations', 'Settings', 'Limits', 'Runtime']);
    });

    it('offers only Overview and Organizations for a plugin without a backend', () => {
        render(withBackend(false));

        expect(tabLabels()).toEqual(['Overview', 'Organizations']);
    });
});
