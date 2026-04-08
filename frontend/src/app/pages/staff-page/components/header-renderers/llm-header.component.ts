import { Component } from '@angular/core';
import { IHeaderParams } from 'ag-grid-community';

@Component({
    selector: 'app-llm-header',
    standalone: true,
    template: `
        <div class="header-container">
            <svg
                xmlns="http://www.w3.org/2000/svg"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1"
                stroke-linecap="round"
                stroke-linejoin="round"
                class="icon icon-tabler icons-tabler-outline icon-tabler-cube"
            >
                <path stroke="none" d="M0 0h24v24H0z" fill="none" />
                <path
                    d="M21 16.008v-8.018a1.98 1.98 0 0 0 -1 -1.717l-7 -4.008a2.016 2.016 0 0 0 -2 0l-7 4.008c-.619 .355 -1 1.01 -1 1.718v8.018c0 .709 .381 1.363 1 1.717l7 4.008a2.016 2.016 0 0 0 2 0l7 -4.008c.619 -.355 1 -1.01 1 -1.718z"
                />
                <path d="M12 22v-10" />
                <path d="M12 12l8.73 -5.04" />
                <path d="M3.27 6.96l8.73 5.04" />
            </svg>
            <span class="title">LLM</span>
        </div>
    `,
    styles: [
        `
            :host {
                width: 100%;
                display: flex;
                align-items: center;

                padding-right: 3px;
            }
            .header-container {
                display: flex;
                align-items: center;
            }
            .icon {
                height: 24px;
                width: 24px;
                margin-right: 10px; /* Space between icon and title */
            }
            .title {
                font-size: 16px;
                font-weight: 500;
            }
        `,
    ],
})
export class LlmHeaderComponent {
    params!: IHeaderParams;

    agInit(params: IHeaderParams): void {
        this.params = params;
    }

    refresh(params: IHeaderParams): boolean {
        void params;
        return false;
    }
}
