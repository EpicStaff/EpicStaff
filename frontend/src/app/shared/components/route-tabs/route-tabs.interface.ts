export interface RouteTab {
    routerLink: string;
    /** SVG sprite icon name for `<app-svg-icon>`. Mutually exclusive with `iconClass`. */
    icon?: string;
    /** Tabler icon-font class, e.g. `'ti ti-webhook'`. Mutually exclusive with `icon`. */
    iconClass?: string;
    label: string;
    /** `data-tour` attribute value, so a guided tour can point at this tab (e.g. the Quick Start tour). */
    tourAnchor?: string;
    /** Function (not boolean) so signal reads inside happen at template-eval time.
     *  Ensures tab visibility refreshes when active-org permissions reload after an org switch. */
    isPermitted: () => boolean;
}
