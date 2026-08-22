import { ConfigureModelsTabId } from '../enums/configure-models-tab-id.enum';

export interface ConfigureModelsTab {
    id: ConfigureModelsTabId;
    label: string;
    /** Tabler icon-font class, e.g. 'ti ti-bolt'. Mutually exclusive with `svgIcon`. */
    iconClass?: string;
    /** app-svg-icon `icon` input. Mutually exclusive with `iconClass`. */
    svgIcon?: string;
    isPermitted: boolean;
}
