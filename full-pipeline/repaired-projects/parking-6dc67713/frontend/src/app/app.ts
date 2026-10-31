import { Component, OnInit, OnDestroy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { GeneratedPanel } from './generated/generated-panel';
import { configureProductApi, productFetch } from './product-api';

type Field={name:string,type:string,required:boolean};
type Entity={name:string,fields:Field[]};
@Component({selector:'app-root',standalone:true,imports:[CommonModule,FormsModule,MatButtonModule,MatCardModule,MatFormFieldModule,MatInputModule,MatSelectModule,MatProgressBarModule,GeneratedPanel],templateUrl:'./app.html'})
export class AppComponent implements OnInit,OnDestroy {
  spec:any; role=''; roles:string[]=[]; token=sessionStorage.getItem('demo-token')||'';
  loggedRole=sessionStorage.getItem('demo-role')||''; page='application'; error=''; notice=''; loading=true;
  entity:Entity|undefined; records:any[]=[]; form:Record<string,any>={}; editing='';
  zones:any[]=[]; active:any={}; history:any[]=[]; events:any[]=[]; duration=60;
  longitude=30.315; latitude=59.935; zoneId='A'; zoneName='Новая зона'; zoneRate=100;
  zoneCoordinates='[[30.33,59.93],[30.34,59.93],[30.34,59.94],[30.33,59.94],[30.33,59.93]]';
  timer:any;
  constructor(private cd:ChangeDetectorRef){}
  get parking(){return (this.spec?.capabilities||[]).some((x:string)=>x.toLowerCase().includes('parking'));}
  get focused(){return this.spec?.uiMode==='focused';}
  get requiresLogin(){return this.spec?.requiresLogin!==false;}
  get hasRecords(){return !this.focused && !!this.spec?.entities?.length;}
  get admin(){return this.loggedRole==='admin';}
  get publicRole(){return this.parking?'driver':(this.spec?.roles||[]).find((r:string)=>r==='user')||(this.spec?.roles||[]).find((r:string)=>r!=='admin')||'user';}
  get purpose(){return this.spec?.businessGoal||this.spec?.summary||'';}
  async ngOnInit(){
    await this.perform(()=>this.initialize());
    this.timer=setInterval(()=>{if(this.token&&this.parking&&this.page==='parking'&&!this.loading)this.perform(()=>this.loadParking(),true);},5000);
  }
  ngOnDestroy(){clearInterval(this.timer);}
  async initialize(){
    this.spec=await this.api('/api/schema');
    document.title=this.spec.title||'Приложение';
    this.roles=[...new Set<string>([...(this.spec.roles||[]),...(!this.focused?['admin']:[]),...(this.parking?['driver']:[])])];
    this.role=this.parking?'driver':this.roles[0]||'user';
    this.entity=this.spec.entities?.[0];
    this.page=this.parking?'parking':'application';
    configureProductApi(this.publicRole,!this.requiresLogin);
    if(!this.requiresLogin)await this.authenticate(this.publicRole);
    if(this.token && this.parking)await this.loadParking();
  }
  async api(path:string,method='GET',body?:any){
    const res=await productFetch(path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
    if(!res.ok){
      let detail='';try{const data=await res.json();detail=data.error||data.message||'';}catch{}
      if(res.status===401){this.clearSession();detail='Сессия завершена. Повторите подключение.';}
      throw new Error(detail||'Не удалось выполнить действие. Попробуйте еще раз.');
    }
    return res.status===204?null:res.json();
  }
  async perform(task:()=>Promise<void>,quiet=false){
    if(!quiet){this.loading=true;this.error='';this.notice='';}
    try{await task();}catch(e:any){this.error=e instanceof TypeError?'Не удалось подключиться. Проверьте соединение и повторите попытку.':e.message||'Не удалось выполнить действие.';}
    finally{if(!quiet)this.loading=false;this.cd.markForCheck();}
  }
  async retry(){
    if(!this.spec||!this.token&&!this.requiresLogin){await this.perform(()=>this.initialize());return;}
    await this.perform(()=>this.page==='parking'?this.loadParking():this.page==='records'?this.loadRecords():this.initialize());
  }
  async authenticate(role:string){
    const data=await this.api('/api/auth/login','POST',{role});
    this.token=data.token;this.loggedRole=data.role;
    sessionStorage.setItem('demo-token',this.token);sessionStorage.setItem('demo-role',this.loggedRole);
  }
  async login(){await this.perform(async()=>{await this.authenticate(this.role);if(this.parking)await this.loadParking();});}
  clearSession(){this.token='';this.loggedRole='';sessionStorage.removeItem('demo-token');sessionStorage.removeItem('demo-role');}
  logout(){this.clearSession();this.error='';this.notice='';this.records=[];this.form={};this.editing='';this.active={};this.history=[];this.events=[];this.page=this.parking?'parking':'application';}
  async navigate(page:string){this.page=page;this.error='';this.notice='';if(page==='records')await this.perform(()=>this.loadRecords());else if(page==='parking')await this.perform(()=>this.loadParking());}
  async selectEntity(name:string){this.entity=this.spec?.entities?.find((e:Entity)=>e.name===name);this.form={};this.editing='';await this.perform(()=>this.loadRecords());}
  async loadRecords(){this.records=this.entity?await this.api('/api/entities/'+encodeURIComponent(this.entity.name)):[];}
  edit(row:any){this.form={...row.data};this.editing=row.id;}
  async save(){if(!this.entity)return;await this.perform(async()=>{const data:Record<string,any>={};for(const f of this.entity!.fields){const value=this.form[f.name];if(value===''||value===undefined||value===null)continue;data[f.name]=f.type==='integer'||f.type==='number'?Number(value):f.type==='boolean'?value===true||value==='true':f.type==='datetime'?new Date(value).toISOString():value;}await this.api('/api/entities/'+encodeURIComponent(this.entity!.name)+(this.editing?'/'+this.editing:''),this.editing?'PUT':'POST',data);this.form={};this.editing='';await this.loadRecords();this.notice='Запись сохранена';});}
  async remove(id:string){if(!this.entity)return;await this.perform(async()=>{await this.api('/api/entities/'+encodeURIComponent(this.entity!.name)+'/'+id,'DELETE');await this.loadRecords();});}
  async loadParking(){[this.zones,this.active,this.history,this.events]=await Promise.all(['/api/parking/zones','/api/parking/active','/api/parking/history','/api/parking/events'].map(p=>this.api(p)));}
  async position(lon=this.longitude,lat=this.latitude){this.longitude=lon;this.latitude=lat;await this.perform(async()=>{const r=await this.api('/api/parking/position','POST',{longitude:Number(lon),latitude:Number(lat)});await this.loadParking();this.notice=r.paymentAdvice?'Зона изменилась. Проверьте оплату; действующая сессия сохранена.':'Местоположение обновлено';});}
  gps(){if(!navigator.geolocation){this.error='Геолокация недоступна';return;}navigator.geolocation.getCurrentPosition(p=>this.position(p.coords.longitude,p.coords.latitude),e=>{this.error=e.message;this.cd.markForCheck();},{enableHighAccuracy:true,timeout:15000});}
  async startSession(){await this.perform(async()=>{await this.api('/api/parking/sessions','POST',{zoneId:this.active.position?.zoneId,durationMinutes:Number(this.duration),confirmDemoPayment:true});await this.loadParking();this.notice='Демонстрационная сессия подтверждена. Реальные деньги не списаны.';});}
  async stopSession(){await this.perform(async()=>{await this.api('/api/parking/sessions/'+this.active.session.id+'/stop','POST',{});await this.loadParking();});}
  async advance(){await this.perform(async()=>{await this.api('/api/parking/clock','POST',{advanceSeconds:300});await this.loadParking();this.notice='Контрольные часы переведены на 5 минут вперед';});}
  async saveZone(){await this.perform(async()=>{await this.api('/api/parking/zones','POST',{id:this.zoneId,name:this.zoneName,rate:Number(this.zoneRate),coordinates:JSON.parse(this.zoneCoordinates)});await this.loadParking();this.notice='Граница и тариф зоны сохранены';});}
  bounds(){const pts=this.zones.flatMap(z=>z.geometry.coordinates[0]) as number[][];if(!pts.length)return [30.30,59.92,30.34,59.95];const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);const dx=Math.max(maxX-minX,0.001)*0.15,dy=Math.max(maxY-minY,0.001)*0.25;return [minX-dx,minY-dy,maxX+dx,maxY+dy];}
  projectX(x:number){const b=this.bounds();return (x-b[0])/(b[2]-b[0])*350;}
  projectY(y:number){const b=this.bounds();return (b[3]-y)/(b[3]-b[1])*200;}
  points(zone:any){return zone.geometry.coordinates[0].map((p:number[])=>`${this.projectX(p[0])},${this.projectY(p[1])}`).join(' ');}
  labelX(zone:any){const xs=zone.geometry.coordinates[0].map((p:number[])=>p[0]);return this.projectX((Math.min(...xs)+Math.max(...xs))/2);}
  labelY(zone:any){const ys=zone.geometry.coordinates[0].map((p:number[])=>p[1]);return this.projectY((Math.min(...ys)+Math.max(...ys))/2);}
  markerX(){return this.projectX(Number(this.active.position?.longitude??this.longitude));}
  markerY(){return this.projectY(Number(this.active.position?.latitude??this.latitude));}
  inputType(field:Field){return field.type==='integer'||field.type==='number'?'number':field.type==='datetime'?'datetime-local':'text';}
}
