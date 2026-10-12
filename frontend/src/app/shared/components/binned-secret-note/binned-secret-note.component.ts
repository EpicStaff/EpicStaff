import { Component, computed, inject, input } from '@angular/core';

import { SecretsStorageService } from '../../services/secrets/secrets-storage.service';

/** Says, under a secret picker, that a selected secret is in the recycle bin and how to fix it. */
@Component({
    selector: 'app-binned-secret-note',
    templateUrl: './binned-secret-note.component.html',
    styleUrls: ['./binned-secret-note.component.scss'],
})
export class BinnedSecretNoteComponent {
    readonly selected = input<number | number[] | null | undefined>(null);
    /** Read-only viewers can't restore or pick, so they only get the first sentence. */
    readonly readonly = input<boolean>(false);

    protected readonly hasBinned = computed(() => {
        const selected = this.selected();
        const ids = Array.isArray(selected) ? selected : selected == null ? [] : [selected];
        return ids.some((id) => this.secretsStorageService.isBinned(id));
    });

    private readonly secretsStorageService = inject(SecretsStorageService);
}
