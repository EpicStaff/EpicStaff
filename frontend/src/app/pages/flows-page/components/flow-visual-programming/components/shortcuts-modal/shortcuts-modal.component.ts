import { Component, input, output, signal } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface ShortcutRow {
  id: string;
  label: string;
  keys: string[];
  hidden?: boolean;
  dividerAfter?: boolean;
}

export interface ShortcutSection {
  id: string;
  title: string;
  rows: ShortcutRow[];
}

@Component({
  selector: 'app-shortcuts-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './shortcuts-modal.component.html',
  styleUrl: './shortcuts-modal.component.scss',
})
export class ShortcutsModalComponent {
  open = input<boolean>(false);
  pos = input<{ top: number; left: number } | null>(null);

  title = input<string>('');
  iconSrc = input<string | null>(null);
  showClose = input<boolean>(true);
  sections = input<ShortcutSection[]>([]);

  closed = output<void>();

  size = signal<'wide' | 'compact'>('wide');
  isMediaLocked = signal(false);

  constructor() {
    const mq = window.matchMedia('(max-width: 1200px)');

    const sync = () => {
      this.isMediaLocked.set(mq.matches);
      if (mq.matches) {
        this.size.set('compact');
      }
    };

    sync();

    const handler = () => sync();
    mq.addEventListener?.('change', handler);
  }

  toggleSize(): void {
    if (this.isMediaLocked()) return;
      this.size.update(s => (s === 'wide' ? 'compact' : 'wide'));
  }
}
