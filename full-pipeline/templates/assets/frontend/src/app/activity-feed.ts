import { ChangeDetectorRef, Component, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { productFetch } from './product-api';

@Component({selector:'activity-feed',standalone:true,imports:[CommonModule],template:`
  <aside class="journal" aria-label="Журнал действий">
    <button class="toggle" type="button" (click)="toggle()" [attr.aria-expanded]="opened">Журнал действий <span aria-hidden="true">{{opened ? '−' : '+'}}</span></button>
    <div class="content" *ngIf="opened" aria-live="polite">
      <p *ngIf="error" role="alert">{{error}}</p><p *ngIf="!error && !items.length">{{loading ? 'Загружаем…' : 'Пока нет завершённых действий.'}}</p>
      <ol *ngIf="items.length"><li *ngFor="let item of items"><span>{{item.label}}</span><time>{{item.occurredAt | date:'dd.MM HH:mm:ss'}}</time></li></ol>
    </div>
  </aside>`,styles:[`
  :host{display:block;margin-top:24px}.journal{border-top:1px solid var(--product-line,#e2e8f0);padding-top:12px;color:var(--product-muted,#64748b)}
  .toggle{width:100%;display:flex;justify-content:space-between;align-items:center;border:0;background:transparent;color:inherit;font:inherit;cursor:pointer;padding:10px 0;text-align:left}
  .toggle:focus-visible{outline:2px solid var(--product-primary,#2563eb);outline-offset:4px}.content{font-size:13px}.content ol{list-style:none;padding:0;margin:8px 0}
  .content li{display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid var(--product-line,#e2e8f0)}.content li span{overflow-wrap:anywhere}.content time{white-space:nowrap;font-size:12px}
  @media(max-width:480px){.content li{flex-direction:column;gap:4px}}
  `]})
export class ActivityFeed implements OnDestroy {
  opened=false; loading=false; error=''; items:any[]=[];
  private timer?:ReturnType<typeof setInterval>; private controller?:AbortController;
  constructor(private cd:ChangeDetectorRef){}
  toggle(){
    this.opened=!this.opened;
    if(this.opened){void this.load();this.timer=setInterval(()=>void this.load(),4000);}
    else{clearInterval(this.timer);this.controller?.abort();}
  }
  async load(){
    if(this.loading)return;
    this.loading=true;this.controller=new AbortController();
    try{
      const response=await productFetch('/api/events/activity',{signal:this.controller.signal});
      if(!response.ok)throw new Error('Не удалось загрузить журнал.');
      this.items=await response.json();this.error='';
    }catch(error:any){if(error.name!=='AbortError')this.error='Не удалось обновить журнал. Повторяем подключение…';}
    finally{this.loading=false;this.cd.markForCheck();}
  }
  ngOnDestroy(){clearInterval(this.timer);this.controller?.abort();}
}
