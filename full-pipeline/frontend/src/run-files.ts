import { Component, EventEmitter, Input, OnChanges, OnDestroy, Output, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Run, RunFile, RunFileContent, RunFileList } from './models';

interface TreeRow { path: string; name: string; depth: number; folder: boolean; file?: RunFile; }
interface TaskSection { label: string; text: string; }

@Component({
  selector: 'app-run-files', standalone: true, imports: [CommonModule, FormsModule],
  templateUrl: './run-files.html', styleUrl: './run-files.css',
})
export class RunFilesComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) run!: Run;
  @Input() view: 'files' | 'task' = 'files';
  @Output() countChange = new EventEmitter<number>();
  readonly files = signal<RunFile[]>([]);
  readonly selectedPath = signal('');
  readonly selectedFile = computed(() => this.files().find(file => file.path === this.selectedPath()) || null);
  readonly preview = signal<RunFileContent | null>(null);
  readonly lines = computed(() => this.preview()?.content.split('\n') || []);
  readonly listLoading = signal(false);
  readonly contentLoading = signal(false);
  readonly listError = signal('');
  readonly contentError = signal('');
  readonly copyMessage = signal('');
  readonly excludedDirectories = signal<string[]>([]);
  readonly query = signal('');
  readonly collapsed = signal(new Set<string>());
  readonly spec = signal<Record<string, unknown> | null>(null);
  readonly specPath = signal('');
  readonly specError = signal('');
  readonly specSections = computed<TaskSection[]>(() => {
    const spec = this.spec();
    if (!spec) return [];
    const analysis = this.record(spec['analysis']);
    const value = (key: string): unknown => spec[key] ?? analysis[key];
    const sections: [string, unknown][] = [
      ['Название приложения', value('title')],
      ['Бизнес-цель', value('businessGoal') ?? value('summary')],
      ['Основное действие', value('primaryAction')],
      ['Формат интерфейса', value('uiMode')],
      ['Экраны', value('screens')],
      ['За рамками задачи', value('outOfScope')],
      ['Требования и критерии приемки', value('requirements')],
      ['Сценарии', value('workflows')],
      ['Роли', value('roles')],
      ['Допущения', value('assumptions')],
      ['Открытые вопросы', value('questions')],
    ];
    return sections.filter(([, item]) => item !== undefined && item !== null && item !== '' && (!Array.isArray(item) || item.length > 0))
      .map(([label, item]) => ({ label, text: this.describe(item) }));
  });
  readonly tree = computed<TreeRow[]>(() => {
    const query = this.query().trim().toLocaleLowerCase();
    const files = this.files().filter(file => !query || file.path.toLocaleLowerCase().includes(query));
    const folders = new Map<string, TreeRow>();
    const rows: TreeRow[] = [];
    for (const file of files) {
      const parts = file.path.split('/');
      for (let depth = 0; depth < parts.length - 1; depth++) {
        const path = parts.slice(0, depth + 1).join('/');
        if (!folders.has(path)) folders.set(path, { path, name: parts[depth], depth, folder: true });
      }
      rows.push({ path: file.path, name: file.name, depth: parts.length - 1, folder: false, file });
    }
    rows.push(...folders.values());
    const sorted = rows.sort((a, b) => this.compareTree(a, b));
    if (query) return sorted;
    const collapsed = this.collapsed();
    return sorted.filter(row => !row.path.split('/').slice(0, -1).some((_, index, parts) => collapsed.has(parts.slice(0, index + 1).join('/'))));
  });
  readonly matchedCount = computed(() => this.files().filter(file => file.path.toLocaleLowerCase().includes(this.query().trim().toLocaleLowerCase())).length);
  private runId = '';
  private epoch = 0;
  private listRequest = 0;
  private contentRequest = 0;
  private specRequest = 0;
  private destroyed = false;

  ngOnChanges(): void {
    if (this.run.runId !== this.runId) {
      this.runId = this.run.runId;
      this.epoch++;
      this.files.set([]); this.selectedPath.set(''); this.preview.set(null); this.spec.set(null); this.specPath.set('');
      this.query.set(''); this.collapsed.set(new Set()); this.listError.set(''); this.contentError.set(''); this.specError.set('');
      this.copyMessage.set(''); this.contentLoading.set(false); this.countChange.emit(0);
    }
    void this.refresh();
  }
  ngOnDestroy(): void { this.destroyed = true; this.epoch++; }
  private current(epoch: number): boolean { return !this.destroyed && this.epoch === epoch; }
  private baseUrl(): string { return `/api/runs/${encodeURIComponent(this.runId)}/files`; }
  contentUrl(path: string): string { return `${this.baseUrl()}/content?path=${encodeURIComponent(path)}`; }
  downloadUrl(path: string): string { return `${this.baseUrl()}/download?path=${encodeURIComponent(path)}`; }
  archiveUrl(): string { return `/api/runs/${encodeURIComponent(this.runId)}/download`; }
  private async request<T>(url: string): Promise<T> {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Сервис вернул ошибку ${response.status}. Повторите загрузку.`);
    return response.json() as Promise<T>;
  }
  private message(error: unknown): string { return error instanceof TypeError ? 'Нет связи с API. Сохраненные данные остаются на экране.' : error instanceof Error ? error.message : 'Не удалось загрузить файл.'; }
  async refresh(): Promise<void> {
    const epoch = this.epoch;
    const request = ++this.listRequest;
    this.listLoading.set(true);
    try {
      const inventory = await this.request<RunFileList>(this.baseUrl());
      if (!this.current(epoch) || request !== this.listRequest) return;
      this.files.set(inventory.items); this.excludedDirectories.set(inventory.excludedDirectories || []);
      this.countChange.emit(inventory.items.length); this.listError.set('');
      const previous = this.selectedPath();
      const selected = inventory.items.find(file => file.path === previous);
      const preferred = selected || inventory.items.find(file => file.path === 'requirements.md')
        || inventory.items.find(file => file.path === 'app-spec.json')
        || inventory.items.find(file => file.viewable && !file.restricted) || inventory.items[0];
      if (preferred) {
        if (preferred.path !== previous) { this.reveal(preferred.path); this.preview.set(null); this.contentError.set(''); this.copyMessage.set(''); }
        this.selectedPath.set(preferred.path);
      } else { this.selectedPath.set(''); this.preview.set(null); this.contentError.set(''); }
      const spec = inventory.items.find(file => file.path === 'app-spec.json') || inventory.items.find(file => file.path.endsWith('/app-spec.json'));
      if (!spec || spec.restricted || !spec.viewable) { this.specRequest++; this.spec.set(null); this.specPath.set(''); this.specError.set(''); }
      await Promise.allSettled([preferred ? this.loadSelected(preferred, epoch) : Promise.resolve(), spec && spec.viewable && !spec.restricted ? this.loadSpec(spec, epoch) : Promise.resolve()]);
    } catch (error) { if (this.current(epoch) && request === this.listRequest) this.listError.set(this.message(error)); }
    finally { if (this.current(epoch) && request === this.listRequest) this.listLoading.set(false); }
  }
  toggleFolder(path: string): void {
    this.collapsed.update(current => { const next = new Set(current); next.has(path) ? next.delete(path) : next.add(path); return next; });
  }
  isCollapsed(path: string): boolean { return !this.query().trim() && this.collapsed().has(path); }
  collapseAll(): void {
    this.collapsed.set(new Set(this.files().flatMap(file => file.path.split('/').slice(0, -1).map((_, index, parts) => parts.slice(0, index + 1).join('/')))));
  }
  expandAll(): void { this.collapsed.set(new Set()); }
  private reveal(path: string): void {
    this.collapsed.update(current => { const next = new Set(current); path.split('/').slice(0, -1).forEach((_, index, parts) => next.delete(parts.slice(0, index + 1).join('/'))); return next; });
  }
  selectFile(file: RunFile): void {
    if (file.path !== this.selectedPath()) { this.preview.set(null); this.contentError.set(''); this.copyMessage.set(''); }
    this.selectedPath.set(file.path);
    void this.loadSelected(file, this.epoch);
  }
  private async loadSelected(file: RunFile, epoch: number): Promise<void> {
    const request = ++this.contentRequest;
    if (!file.viewable || file.restricted) { this.preview.set(null); this.contentLoading.set(false); this.contentError.set(''); return; }
    this.contentLoading.set(true);
    try {
      const content = await this.request<RunFileContent>(this.contentUrl(file.path));
      if (!this.current(epoch) || this.selectedPath() !== file.path || request !== this.contentRequest) return;
      this.preview.set(content); this.contentError.set('');
    } catch (error) { if (this.current(epoch) && this.selectedPath() === file.path && request === this.contentRequest) this.contentError.set(this.message(error)); }
    finally { if (this.current(epoch) && request === this.contentRequest) this.contentLoading.set(false); }
  }
  private async loadSpec(file: RunFile, epoch: number): Promise<void> {
    const request = ++this.specRequest;
    try {
      const content = await this.request<RunFileContent>(this.contentUrl(file.path));
      if (!this.current(epoch) || request !== this.specRequest) return;
      if (content.truncated) throw new Error('Спецификация слишком большая для полного разбора. Откройте или скачайте app-spec.json во вкладке «Файлы».');
      const parsed: unknown = JSON.parse(content.content);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('В app-spec.json ожидается объект спецификации.');
      this.spec.set(parsed as Record<string, unknown>); this.specPath.set(file.path); this.specError.set('');
    } catch (error) { if (this.current(epoch) && request === this.specRequest) this.specError.set(error instanceof SyntaxError ? 'Спецификация пока содержит неполный JSON. Дождитесь обновления или откройте файл.' : this.message(error)); }
  }
  async copyCode(): Promise<void> {
    const preview = this.preview(); if (!preview) return;
    const path = this.selectedPath();
    try { await navigator.clipboard.writeText(preview.content); if (path === this.selectedPath()) this.copyMessage.set(preview.truncated ? 'Скопирован показанный фрагмент' : 'Код скопирован'); }
    catch { if (path === this.selectedPath()) this.copyMessage.set('Не удалось скопировать. Выделите текст вручную.'); }
  }
  sizeLabel(size: number): string { return size < 1024 ? `${size} Б` : size < 1024 * 1024 ? `${(size / 1024).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} КБ` : `${(size / (1024 * 1024)).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} МБ`; }
  kindLabel(kind: string): string { return ({ source: 'Исходник', report: 'Отчет', config: 'Конфигурация', archive: 'Архив', other: 'Файл' } as Record<string, string>)[kind] || 'Файл'; }
  private compareTree(a: TreeRow, b: TreeRow): number {
    const left = a.path.split('/'); const right = b.path.split('/');
    for (let index = 0; index < Math.min(left.length, right.length); index++) {
      const leftFolder = index < left.length - 1 || a.folder;
      const rightFolder = index < right.length - 1 || b.folder;
      if (leftFolder !== rightFolder) return leftFolder ? -1 : 1;
      const compared = left[index].localeCompare(right[index]);
      if (compared) return compared;
    }
    return left.length - right.length;
  }
  private record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
  private describe(value: unknown): string {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(item => `• ${this.describe(item)}`).join('\n\n');
    if (value && typeof value === 'object') {
      const labels: Record<string, string> = { id: 'ID', name: 'Название', title: 'Название', description: 'Описание', acceptance: 'Критерии приемки', requirementIds: 'Требования', question: 'Вопрос', critical: 'Критический', purpose: 'Назначение', primaryAction: 'Основное действие', route: 'Путь', fields: 'Поля', actions: 'Действия' };
      return Object.entries(value).map(([key, item]) => `${labels[key] || key}: ${this.describe(item)}`).join('\n');
    }
    return typeof value === 'boolean' ? value ? 'Да' : 'Нет' : value == null ? '—' : String(value);
  }
}
