import { Component, computed, input } from '@angular/core';

/** One line of a preview list: what it is, and a short note beside it. */
export interface PluginPreviewItemView {
    /** Unique within its list. */
    key: string;
    name: string;
    detail: string | null;
}

/** The items a list shows, and how many more the server counted but did not send. */
export interface PluginPreviewListView {
    items: PluginPreviewItemView[];
    moreCount: number;
}

/**
 * A titled list of what an action affects, ending with "and N more" when the list was cut short. With `emptyText`
 * an empty list says so; `emphasised` makes the section stand out; `hint` adds a note under the list.
 */
@Component({
    selector: 'app-plugin-preview-section',
    templateUrl: './plugin-preview-section.component.html',
    styleUrl: './plugin-preview-section.component.scss',
})
export class PluginPreviewSectionComponent {
    readonly heading = input.required<string>();
    readonly list = input.required<PluginPreviewListView>();
    readonly emptyText = input<string | null>(null);
    readonly emphasised = input(false);
    readonly hint = input<string | null>(null);

    protected readonly isEmpty = computed(() => this.list().items.length === 0);
}
