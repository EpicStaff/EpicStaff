import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginSummary } from '../../models/plugin-admin.model';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginSummary } from '../../testing/plugin-fixtures';
import { PluginsAdminPageComponent } from './plugins-admin-page.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('PluginsAdminPageComponent', () => {
    let fixture: ComponentFixture<PluginsAdminPageComponent>;
    let element: HTMLElement;

    function render(plugins: PluginSummary[]): void {
        TestBed.configureTestingModule({
            imports: [PluginsAdminPageComponent],
            providers: [
                provideRouter([]),
                {
                    provide: PluginsAdminStorageService,
                    useValue: { plugins: signal(plugins), isLoading: signal(false), loadPlugins: () => of(plugins) },
                },
                { provide: PluginDialogsService, useValue: {} },
                { provide: ToastService, useValue: { error: vi.fn() } },
            ],
        });
        fixture = TestBed.createComponent(PluginsAdminPageComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    }

    /** The badges of the State cell of the plugin's row. */
    function stateBadges(name: string): string[] {
        const row = Array.from(element.querySelectorAll('.table-body .table-row')).find((candidate) =>
            candidate.textContent?.includes(name)
        )!;
        return Array.from(row.querySelectorAll('.state-badges app-plugin-badge')).map(
            (badge) => badge.textContent?.trim() ?? ''
        );
    }

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

    afterEach(() => vi.unstubAllGlobals());

    it('names an uninstalled and a deleting plugin, and marks one that needs attention', () => {
        render([
            buildPluginSummary({ identifier: 'atlas', name: 'Atlas' }),
            buildPluginSummary({
                identifier: 'beacon',
                name: 'Beacon',
                state: 'uninstalling',
                purge_after: '2026-11-20T09:00:00Z',
            }),
            buildPluginSummary({ identifier: 'comet', name: 'Comet', state: 'purging', needs_attention: true }),
        ]);

        expect(stateBadges('Atlas')).toEqual(['Running']);
        expect(stateBadges('Beacon')).toEqual(['Uninstalled']);
        expect(stateBadges('Comet')).toEqual(['Deleting', 'Needs attention']);
    });
});
