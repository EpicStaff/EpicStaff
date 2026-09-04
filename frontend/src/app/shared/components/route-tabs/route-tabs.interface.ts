export interface RouteTab {
    routerLink: string;
    icon: string;
    label: string;
    /** Function (not boolean) so signal reads inside happen at template-eval time.
     *  Ensures tab visibility refreshes when active-org permissions reload after an org switch. */
    isPermitted: () => boolean;
}
