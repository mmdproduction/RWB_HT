import { Injectable } from '@angular/core';

export interface AppSpec {
  appName: string;
  description: string;
  roles: string[];
  entities: {
    name: string;
    label: string;
    fields: { name: string; label: string; type: string }[];
    mockData: Record<string, any>[];
  }[];
  scenarios: string[];
  generatedAt: string;
}

@Injectable({ providedIn: 'root' })
export class SpecGeneratorService {
  private defaultSpec: AppSpec = {
    appName: 'Парковочный помощник',
    description: 'Система управления парковкой',
    roles: ['Водитель', 'Администратор'],
    entities: [
      {
        name: 'zones',
        label: 'Зоны',
        fields: [
          { name: 'id', label: 'ID', type: 'number' },
          { name: 'name', label: 'Название', type: 'string' },
          { name: 'capacity', label: 'Вместимость', type: 'number' }
        ],
        mockData: [
          { id: 1, name: 'Центр', capacity: 150 },
          { id: 2, name: 'Парк', capacity: 50 }
        ]
      }
    ],
    scenarios: ['Поиск места', 'Оплата'],
    generatedAt: new Date().toISOString()
  };

  generateSpec(requirements: string): AppSpec {
    const text = requirements.toLowerCase();
    const appName = this.extractAppName(text) || 'Сгенерированное приложение';
    const roles = this.extractRoles(text);
    const entities = this.extractEntities(text);
    const scenarios = this.extractScenarios(text);
    
    return {
      appName,
      description: requirements,
      roles: roles.length > 0 ? roles : this.defaultSpec.roles,
      entities: entities.length > 0 ? entities : this.defaultSpec.entities,
      scenarios: scenarios.length > 0 ? scenarios : this.defaultSpec.scenarios,
      generatedAt: new Date().toISOString()
    };
  }

  private extractAppName(text: string): string | null {
    const match = text.match(/(?:система|приложение|платформа|сервис)\s+([^.,]+?)(?:\s+для|\s*,|\s*$)/i);
    if (match) return match[1].trim().split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    return null;
  }

  private extractRoles(text: string): string[] {
    const roles: string[] = [];
    const match = text.match(/роли?:\s*([^.,;]+)/i);
    if (match) {
      match[1].split(/[,;]/).forEach(r => {
        const role = r.trim();
        if (role.length > 2 && !roles.includes(role)) roles.push(role.charAt(0).toUpperCase() + role.slice(1));
      });
    }
    return roles;
  }

  private extractEntities(text: string): AppSpec['entities'] {
    const entities: AppSpec['entities'] = [];
    const match = text.match(/сущност[иях]+?:\s*([^.,;]+)/i);
    if (match) {
      match[1].split(/[,;]/).forEach(item => {
        const name = item.trim().toLowerCase();
        if (name.length > 2 && !entities.find(e => e.name === name)) {
          entities.push({
            name,
            label: name.charAt(0).toUpperCase() + name.slice(1),
            fields: [{ name: 'id', label: 'ID', type: 'number' }, { name: 'name', label: 'Название', type: 'string' }],
            mockData: [{ id: 1, name: 'Пример 1' }, { id: 2, name: 'Пример 2' }]
          });
        }
      });
    }
    return entities;
  }

  private extractScenarios(text: string): string[] {
    const scenarios: string[] = [];
    const match = text.match(/сценари[иях]+?:\s*([^.,;]+)/i);
    if (match) {
      match[1].split(/[,;]/).forEach(item => {
        const s = item.trim();
        if (s.length > 3 && !scenarios.includes(s)) scenarios.push(s.charAt(0).toUpperCase() + s.slice(1));
      });
    }
    return scenarios;
  }
}