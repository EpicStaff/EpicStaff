import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    HostListener,
    inject,
    input,
    OnDestroy,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { GraphCollaborationWsService } from 'src/app/features/flows/services/graph-collaboration.ws.service';
import { ProfileService } from 'src/app/services/auth/profile.service';

import { getAvatarColor } from '../../core/helpers/avatar-colors';
import { SidePanelService } from '../../services/side-panel.service';

@Component({
    selector: 'app-lockable-field',
    standalone: true,
    imports: [MatTooltipModule],
    template: `
        <ng-content></ng-content>
        @if (fieldLock()) {
            <div
                class="lock-indicator"
                [style.background]="lockColor()"
                [matTooltip]="'Editing by ' + (fieldLock()?.display_name ?? 'User')"
                matTooltipPosition="above"
            >
                {{ initials() }}
            </div>
        }
    `,
    styles: [
        `
            :host {
                display: block;
                position: relative;
            }
            :host(.fill) {
                display: flex;
                flex-direction: column;
                flex: 1 1 auto;
                align-self: stretch;
                min-height: 0;
                min-width: 0;
            }
            :host.locked-by-other {
                pointer-events: none;
                outline: 2px solid var(--field-lock-color);
                border-radius: 6px;
                box-shadow: 0 0 0 4px color-mix(in srgb, var(--field-lock-color) 20%, transparent);
            }
            .lock-indicator {
                position: absolute;
                top: -8px;
                right: -8px;
                width: 20px;
                height: 20px;
                border-radius: 50%;
                color: white;
                font-size: 8px;
                font-weight: 700;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10;
                pointer-events: auto;
                cursor: default;
            }
            /* Inset variant for large container fields whose outer outline and
               indicator would be clipped by a parent with overflow: hidden. */
            :host(.lock-inset).locked-by-other {
                outline: none;
                box-shadow: inset 0 0 0 2px var(--field-lock-color);
            }
            :host(.lock-inset) .lock-indicator {
                top: 8px;
                right: 8px;
            }
        `,
    ],
    host: {
        '[class.locked-by-other]': 'isLockedByOther()',
        '[class.locked-by-me]': 'isLockedByMe()',
        '[style.--field-lock-color]': 'lockColor()',
    },
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LockableFieldComponent implements OnDestroy {
    readonly fieldId = input.required<string>();
    readonly nodeId = input.required<string>();

    private readonly wsService = inject(GraphCollaborationWsService);
    private readonly profileService = inject(ProfileService);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly el = inject(ElementRef<HTMLElement>);

    protected readonly fieldLock = computed(
        () => this.wsService.lockedNodeFields().get(this.nodeId())?.get(this.fieldId()) ?? null
    );

    protected readonly isLockedByOther = computed(() => {
        const lock = this.fieldLock();
        if (!lock) return false;
        return lock.user_id !== this.profileService.currentUserSignal()?.id;
    });

    protected readonly isLockedByMe = computed(() => {
        const lock = this.fieldLock();
        if (!lock) return false;
        return lock.user_id === this.profileService.currentUserSignal()?.id;
    });

    protected readonly lockColor = computed(() => {
        const lock = this.fieldLock();
        return lock ? getAvatarColor(lock.user_id) : null;
    });

    protected readonly initials = computed(() => {
        const lock = this.fieldLock();
        if (!lock?.display_name) return '?';
        const words = lock.display_name.trim().split(/\s+/);
        return words.length >= 2 ? (words[0][0] + words[1][0]).toUpperCase() : words[0].slice(0, 2).toUpperCase();
    });

    @HostListener('focusin')
    onFocusIn(): void {
        if (!this.isLockedByOther()) {
            this.wsService.sendNodeLocked(this.nodeId(), this.fieldId());
        }
    }

    @HostListener('pointerdown')
    onPointerDown(): void {
        if (!this.isLockedByOther()) {
            this.wsService.sendNodeLocked(this.nodeId(), this.fieldId());
        }
    }

    @HostListener('document:pointerdown', ['$event'])
    onDocumentPointerDown(event: PointerEvent): void {
        if (!this.isLockedByMe()) return;
        const target = event.target as Node | null;
        if (target && this.el.nativeElement.contains(target)) return;
        this.wsService.sendNodeUnlocked(this.nodeId(), this.fieldId());
    }

    @HostListener('focusout', ['$event'])
    onFocusOut(event: FocusEvent): void {
        const relatedTarget = event.relatedTarget as Node | null;
        if (relatedTarget && (event.currentTarget as HTMLElement).contains(relatedTarget)) return;
        this.sidePanelService.triggerAutosave();
        setTimeout(() => {
            if (!document.hasFocus()) return;
            if (this.isLockedByMe()) {
                this.wsService.sendNodeUnlocked(this.nodeId(), this.fieldId());
            }
        }, 0);
    }

    @HostListener('window:focus')
    onWindowFocus(): void {
        // User returned from Alt+Tab — re-assert lock if our field is still the active element.
        const hasFocusedChild = this.el.nativeElement.contains(document.activeElement);
        if (hasFocusedChild && !this.isLockedByOther()) {
            this.wsService.sendNodeLocked(this.nodeId(), this.fieldId());
        }
    }

    ngOnDestroy(): void {
        if (this.isLockedByMe()) {
            this.wsService.sendNodeUnlocked(this.nodeId(), this.fieldId());
        }
    }
}
