import { Component, computed, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { AppSvgIconComponent, SearchComponent } from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { isPlainPrimaryClick } from '@shared/utils';

import { AvailablePlugin } from '../../models/available-plugin.model';
import { PLUGIN_PAGE_ROUTE_SEGMENT } from '../../pages/plugin-host-page/plugin-page.matcher';
import { PluginIconComponent } from '../plugin-icon/plugin-icon.component';

/** A popover lists more apps than this with a search field above them. */
export const APPS_LIST_SEARCH_THRESHOLD = 6;

/** `popover`: a panel of its own, with a heading; `inline`: under its row in the sidebar drawer. */
export type AppsListVariant = 'popover' | 'inline';

const NO_NEW_APPS: ReadonlySet<string> = new Set();

/**
 * The apps a user may open in the active organization, each a link to its page (so a middle click opens it in a new
 * tab), with its icon, name and description. The sidebar shows it for its Apps row and its app switcher, as a popover
 * or inline in its drawer. What goes under the list (Manage apps, Open in a new tab) is projected in.
 */
@Component({
    selector: 'app-apps-list',
    imports: [
        RouterLink,
        AppSvgIconComponent,
        SearchComponent,
        PluginIconComponent,
        MatTooltipModule,
        TooltipOnOverflowDirective,
    ],
    templateUrl: './apps-list.component.html',
    styleUrl: './apps-list.component.scss',
    host: {
        '[class.apps-list--popover]': "variant() === 'popover'",
        '[class.apps-list--inline]': "variant() === 'inline'",
    },
})
export class AppsListComponent {
    /** Sorted as they should show. */
    readonly apps = input.required<readonly AvailablePlugin[]>();
    readonly variant = input<AppsListVariant>('popover');
    /** The popover's heading, and the list's accessible name. */
    readonly heading = input('Apps');
    /** Shown next to a popover's heading. */
    readonly organizationName = input<string | null>(null);
    /** The app the user is in: checked, and `aria-current`. */
    readonly currentIdentifier = input<string | null>(null);
    /** Apps to tag "New". */
    readonly newIdentifiers = input<ReadonlySet<string>>(NO_NEW_APPS);
    /** An app was followed in this page (not opened elsewhere, as in a new tab): its owner may close the list. */
    readonly appChosen = output<void>();

    protected readonly query = signal('');
    protected readonly showsSearch = computed(
        () => this.variant() === 'popover' && this.apps().length > APPS_LIST_SEARCH_THRESHOLD
    );
    protected readonly shownApps = computed(() => {
        const query = this.query().trim().toLocaleLowerCase();
        if (!this.showsSearch() || query === '') return this.apps();
        return this.apps().filter((app) => app.name.toLocaleLowerCase().includes(query));
    });
    protected readonly emptyText = computed(() =>
        this.apps().length === 0 ? 'No apps in this organization' : 'No apps match'
    );

    protected readonly pluginsRoot = `/${PLUGIN_PAGE_ROUTE_SEGMENT}`;

    protected onAppClick(event: MouseEvent): void {
        if (isPlainPrimaryClick(event)) this.appChosen.emit();
    }
}
